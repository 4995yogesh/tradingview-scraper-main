"""
FastAPI backend — TradingView Scraper with SQLite persistent candle storage.

Endpoints:
  GET /api/ohlc?exchange=OANDA&symbol=EURUSD&timeframe=1d&candles=300
  GET /api/indicators?exchange=OANDA&symbol=EURUSD&timeframe=1d&indicators=RSI,Stoch.K
  GET /api/watchlist
  GET /api/db/summary   (diagnostic — shows what's in SQLite)

Startup flow:
  1. Load all stored candles from SQLite → RAM cache (instant)
  2. Background thread gap-fills each timeframe from TradingView (non-blocking)
  3. Server accepts requests immediately — serves from DB while gap-fill runs

OHLC request flow:
  - Fresh RAM cache (< 55 s since last TV fetch) → serve instantly
  - Stale → fetch from TradingView → write to SQLite + RAM → serve
"""

import sys
import os
import time
import threading
import logging
from dotenv import load_dotenv

load_dotenv()

from typing import List, Optional
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# ── Package path setup ────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PIPE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, PIPE)

from tradingview_scraper.symbols.technicals import Indicators
from tradingview_scraper.symbols.historical import HistoricalFetcher
from pipeline.main import pipeline
from pipeline.data.storage import storage
from pipeline.data.db import candle_db          # ← SQLite layer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w", "1M": "1M",
    "1D": "1d", "1W": "1w",
}

# Timeframes stored in SQLite via routine gap-fill (intra-day are derived from 5m)
PERSISTENT_TIMEFRAMES = ["1m", "5m", "1h", "4h", "1d", "1w"]

# Symbols to pre-load and gap-fill on startup
PERSISTENT_SYMBOLS = [("OANDA", "EURUSD")]

# Seconds per bar for each timeframe (used for gap calculation)
TF_INTERVAL_SECS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}

# Per-timeframe fetch limits for routine refreshes (not first-time backfills)
TF_FETCH_LIMIT = {
    "1m": 300, "5m": 400, "15m": 500, "30m": 500,
    "1h": 600, "4h": 700, "1d": 800, "1w": 600, "1M": 300,
}

# Watchlist symbols
WATCHLIST_SYMBOLS = [
    {"exchange": "OANDA", "symbol": "EURUSD"},
]

# Track which series are currently being gap-filled (to avoid double-fetching)
_gap_filling: set = set()
_gap_filling_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_candles_for_ui(raw_candles, timeframe: str):
    """
    Convert raw candle dicts (either 'time' already set, or 'timestamp' from
    HistoricalFetcher / DB) into the exact shape lightweight-charts expects.
    Returns (candle_data, volume_data) sorted ascending, no duplicates.
    """
    use_timestamp = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
    seen_times = set()
    candle_data = []
    volume_data = []

    for c in raw_candles:
        # Accept 'ts' (from DB rows), 'timestamp' (from HistoricalFetcher), or 'time' (RAM storage)
        if "ts" in c:
            ts = int(c["ts"])
            time_val = ts if use_timestamp else datetime.fromtimestamp(ts, tz=IST).strftime("%Y-%m-%d")
        elif "timestamp" in c:
            ts = int(c["timestamp"])
            time_val = ts if use_timestamp else datetime.fromtimestamp(ts, tz=IST).strftime("%Y-%m-%d")
        else:
            time_val = c["time"]

        if time_val in seen_times:
            continue
        seen_times.add(time_val)

        candle_data.append({
            "time":  time_val,
            "open":  round(float(c["open"]),  5),
            "high":  round(float(c["high"]),  5),
            "low":   round(float(c["low"]),   5),
            "close": round(float(c["close"]), 5),
        })
        volume_data.append({
            "time":  time_val,
            "value": float(c.get("volume", 0)),
            "color": "rgba(38,166,154,0.5)" if float(c["close"]) >= float(c["open"]) else "rgba(239,83,80,0.5)",
        })

    candle_data.sort(key=lambda x: x["time"])
    volume_data.sort(key=lambda x: x["time"])
    return candle_data, volume_data


def resample_candles(source_candles: list, target_tf: str) -> list:
    """
    Dynamically aggregate high-density 5m candles into larger timeframes.
    Supports intra-day and macro timeframes.
    Expects source_candles to be chronological.
    """
    tf_minutes = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}.get(target_tf)
    if not tf_minutes or not source_candles:
        return source_candles

    bucket_size_secs = tf_minutes * 60
    buckets = {}

    for c in source_candles:
        ts = int(c.get("ts", c.get("timestamp", c.get("time", 0))))
        if not ts:
            continue
            
        bucket_ts = (ts // bucket_size_secs) * bucket_size_secs
        
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {
                "ts": bucket_ts,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c.get("volume", 0.0))
            }
        else:
            b = buckets[bucket_ts]
            b["high"] = max(b["high"], float(c["high"]))
            b["low"] = min(b["low"], float(c["low"]))
            b["close"] = float(c["close"])
            b["volume"] += float(c.get("volume", 0.0))

    return [buckets[k] for k in sorted(buckets.keys())]


def _seed_storage(exchange: str, symbol: str, timeframe: str,
                  raw_candles: list, prepend: bool = False):
    """
    1. Persist raw candles to SQLite (write-through).
    2. Load them into the in-memory DataStorage deque.
    3. Stamp the last_refresh time so the freshness check works.
    """
    # ── 1. Write to SQLite ────────────────────────────────────────────────────
    candle_db.upsert_candles(exchange, symbol, timeframe, raw_candles)
    candle_db.log_refresh(exchange, symbol, timeframe, int(time.time()))

    # ── 2. Format and push to RAM ─────────────────────────────────────────────
    use_timestamp = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
    formatted = []
    for c in raw_candles:
        ts = int(float(c.get("timestamp", c.get("ts", c.get("time", 0)))))
        if use_timestamp:
            time_val = ts
        else:
            dt = datetime.fromtimestamp(ts, tz=IST)
            time_val = dt.strftime("%Y-%m-%d")

        formatted.append({
            "time":   time_val,
            "open":   float(c["open"]),
            "high":   float(c["high"]),
            "low":    float(c["low"]),
            "close":  float(c["close"]),
            "volume": float(c.get("volume", 0)),
        })

    if prepend:
        storage.prepend_candles(exchange, symbol, timeframe, formatted)
    else:
        for f in formatted:
            storage.append_candle(exchange, symbol, timeframe, f)

    # ── 3. Stamp last refresh ─────────────────────────────────────────────────
    with storage.lock:
        storage._ensure_paths(exchange, symbol, timeframe)
        storage.last_refresh[exchange][symbol][timeframe] = time.time()


def _load_db_into_ram(exchange: str, symbol: str, timeframe: str):
    """
    Pull all rows for a series from SQLite and push them into the RAM deque.
    Called at startup before the server begins accepting requests.
    """
    db_rows = candle_db.get_candles(exchange, symbol, timeframe)
    if not db_rows:
        logger.info("DB empty for %s:%s [%s] — will be filled by gap-fill thread", exchange, symbol, timeframe)
        return

    use_timestamp = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
    storage._ensure_paths(exchange, symbol, timeframe)

    for row in db_rows:
        ts = int(row["ts"])
        time_val = ts if use_timestamp else datetime.fromtimestamp(ts, tz=IST).strftime("%Y-%m-%d")
        storage.candles[exchange][symbol][timeframe].append({
            "time":   time_val,
            "open":   row["open"],
            "high":   row["high"],
            "low":    row["low"],
            "close":  row["close"],
            "volume": row["volume"],
        })

    # Mark as "fresh enough" so the first API hit doesn't immediately re-fetch
    with storage.lock:
        storage._ensure_paths(exchange, symbol, timeframe)
        storage.last_refresh[exchange][symbol][timeframe] = time.time() - 50  # 10 s to re-check

    logger.info("Loaded %d candles from DB → RAM for %s:%s [%s]",
                len(db_rows), exchange, symbol, timeframe)


def _gap_fill(exchange: str, symbol: str, timeframe: str):
    """
    Detect and fill the gap between the newest DB candle and now.
    Runs in a background thread — does not block the server startup.
    """
    key = (exchange, symbol, timeframe)
    with _gap_filling_lock:
        if key in _gap_filling:
            return  # Already running for this series
        _gap_filling.add(key)

    try:
        latest_ts = candle_db.get_latest_ts(exchange, symbol, timeframe)
        now_ts    = int(time.time())
        interval  = TF_INTERVAL_SECS.get(timeframe, 60)

        # Sensible first-time limits per TF (massively bump 5m to drive aggregation)
        FIRST_FETCH = {
            "1m": 2000, "5m": 20000, "1d": 5000, "1w": 2000,
        }

        if latest_ts is None:
            fetch_limit = FIRST_FETCH.get(timeframe, 1000)
            logger.info("[gap-fill] First backfill for %s:%s [%s] limit=%d",
                        exchange, symbol, timeframe, fetch_limit)
        else:
            gap_secs = now_ts - latest_ts
            if gap_secs <= interval * 1.5:
                logger.info("[gap-fill] %s:%s [%s] current (gap=%ds)",
                            exchange, symbol, timeframe, gap_secs)
                return
            missing_bars = gap_secs // interval + 20
            fetch_limit  = max(int(missing_bars), 50)
            logger.info("[gap-fill] %s:%s [%s] gap=%ds → fetching %d bars",
                        exchange, symbol, timeframe, gap_secs, fetch_limit)

        cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
        jwt_value    = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
        fetcher      = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)

        raw_candles = fetcher.fetch_historical_data(
            exchange   = exchange,
            symbol     = symbol,
            timeframe  = timeframe,
            limit      = fetch_limit,
            chunk_size = min(fetch_limit, 5000),
            delay_ms   = 250,
        )

        if raw_candles:
            _seed_storage(exchange, symbol, timeframe, raw_candles)
            logger.info("[gap-fill] ✓ %s:%s [%s] stored=%d DB_total=%d",
                        exchange, symbol, timeframe,
                        len(raw_candles), candle_db.count(exchange, symbol, timeframe))
        else:
            logger.warning("[gap-fill] %s:%s [%s] — TV returned no candles",
                           exchange, symbol, timeframe)

    except Exception as exc:
        logger.error("[gap-fill] %s:%s [%s] failed: %s", exchange, symbol, timeframe, exc)
    finally:
        with _gap_filling_lock:
            _gap_filling.discard(key)


def _run_all_gap_fills():
    """
    Sequential gap-fill, shortest timeframe first so 1m/5m data appears
    quickly for the user. Deep history loads in the background afterward.
    """
    ordered = sorted(
        PERSISTENT_TIMEFRAMES,
        key=lambda tf: TF_INTERVAL_SECS.get(tf, 0),
        reverse=False,  # 1m first, 1w last
    )
    for exchange, symbol in PERSISTENT_SYMBOLS:
        for tf in ordered:
            _gap_fill(exchange, symbol, tf)
            time.sleep(2)   # brief pause between WebSocket sessions


# ── Periodic live refresh (runs every 60 s) ───────────────────────────────────

def _fetch_latest_candles(exchange: str, symbol: str, timeframe: str, limit: int = 20):
    """
    Fetch the very latest `limit` candles from TradingView and merge them
    into SQLite + RAM cache.  Intended to be called by the periodic refresh
    thread so the RAM cache is always < 60 s stale.
    """
    key = (exchange, symbol, timeframe)
    with _gap_filling_lock:
        if key in _gap_filling:
            return   # gap-fill already running; skip
        _gap_filling.add(key)
    try:
        cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
        jwt_value    = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
        fetcher      = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
        raw = fetcher.fetch_historical_data(
            exchange=exchange, symbol=symbol, timeframe=timeframe,
            limit=limit, chunk_size=limit, delay_ms=100,
        )
        if raw:
            _seed_storage(exchange, symbol, timeframe, raw)
            logger.info("[periodic] ✓ %s:%s [%s] refreshed %d candles",
                        exchange, symbol, timeframe, len(raw))
        else:
            logger.warning("[periodic] %s:%s [%s] — TV returned no candles", exchange, symbol, timeframe)
    except Exception as exc:
        logger.error("[periodic] %s:%s [%s] failed: %s", exchange, symbol, timeframe, exc)
    finally:
        with _gap_filling_lock:
            _gap_filling.discard(key)


_stop_refresh = threading.Event()

def _periodic_refresh_loop():
    """
    Background thread: wakes at the top of every minute and refreshes the
    latest candles for every persistent symbol/timeframe pair.
    Uses short-duration fetches (20 bars) so each round-trip is fast.
    """
    # Wait for the initial gap-fill to settle before starting periodic work
    time.sleep(30)
    while not _stop_refresh.is_set():
        now = time.time()
        # Align to the next 15-second boundary
        next_period = (int(now) // 15 + 1) * 15
        sleep_secs  = max(0, next_period - time.time())
        if _stop_refresh.wait(timeout=sleep_secs):
            break   # Stop was requested

        logger.info("[periodic] Running live-candle refresh for all series")
        for exchange, symbol in PERSISTENT_SYMBOLS:
            for tf in PERSISTENT_TIMEFRAMES:
                _fetch_latest_candles(exchange, symbol, tf, limit=20)
                time.sleep(1)   # avoid hammering TV in quick succession


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Start event-driven streaming pipeline
    pipeline.start()

    # 2. Load persisted candles into RAM (fast — pure SQL reads)
    logger.info("=== Loading persisted candle data from SQLite ===")
    for exchange, symbol in PERSISTENT_SYMBOLS:
        for tf in PERSISTENT_TIMEFRAMES:
            _load_db_into_ram(exchange, symbol, tf)

    # 3. Start background gap-fill (non-blocking — server ready immediately)
    gap_thread = threading.Thread(
        target=_run_all_gap_fills,
        name="gap-filler",
        daemon=True,
    )
    gap_thread.start()
    logger.info("=== Gap-fill thread started — server accepting requests ===")

    # 4. Start periodic live refresh (fires at the top of every minute)
    _stop_refresh.clear()
    refresh_thread = threading.Thread(
        target=_periodic_refresh_loop,
        name="periodic-refresh",
        daemon=True,
    )
    refresh_thread.start()
    logger.info("=== Periodic refresh thread started ===")

    yield  # Server is live

    _stop_refresh.set()
    pipeline.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="TradingView Scraper API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/db/summary")
def db_summary():
    """Diagnostic endpoint — shows what's stored in SQLite."""
    rows = candle_db.series_summary()
    return {"status": "ok", "series": rows}


def _sync_tick(payload: dict, exchange: str, symbol: str, timeframe: str, is_recent: bool) -> dict:
    """
    Overwrites the 'close' price of the final candle in any timeframe 
    with the exact real-time close price of the '1m' timeframe.
    This guarantees 100% price parity across all UI panes continuously.
    """
    if not is_recent or timeframe == "1m" or payload.get("status") != "success":
        return payload
    
    cd = payload.get("candleData")
    vd = payload.get("volumeData")
    if not cd:
        return payload
        
    latest_1m = storage.get_candles(exchange, symbol, "1m", count=1)
    if latest_1m:
        tick = latest_1m[0]["close"]
        cd[-1]["close"] = tick
        cd[-1]["high"] = max(cd[-1]["high"], tick)
        cd[-1]["low"] = min(cd[-1]["low"], tick)
        if vd:
            vd[-1]["color"] = "rgba(38,166,154,0.5)" if cd[-1]["close"] >= cd[-1]["open"] else "rgba(239,83,80,0.5)"
            
    return payload


@app.get("/api/ohlc")
def get_ohlc(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    """
    Return OHLCV candles for the given symbol/timeframe.

    Fast path  : serve from RAM cache if data is fresh (< 12 s since last TV fetch).
    Slow path  : fetch from TradingView → persist to SQLite → update RAM → serve.
    Fallback   : if TV fetch fails but DB has data, serve stale DB data rather than 500.
    """
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Unsupported timeframe '{timeframe}'. Choose from: {list(TIMEFRAME_MAP)}")

    if ":" in symbol:
        exchange, symbol = symbol.split(":", 1)

    use_timestamp = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
    parsed_end    = int(end_time) if end_time and use_timestamp else end_time

    logger.info("OHLC → %s:%s tf=%s candles=%d end=%s", exchange, symbol, timeframe, candles, end_time)
    
    is_recent = end_time is None

    # ── Step 0: Aggregation Interception ──────────────────────────────────────
    if timeframe in ["15m", "30m", "1h"]:
        tf_minutes = {"15m": 15, "30m": 30, "1h": 60}[timeframe]
        multiplier = max(1, tf_minutes // 5)
        needed_5m = candles * multiplier + int(multiplier * 0.5)  # 50% buffer for temporal gaps
        
        # 1d and 1w pass `end_time` as a 'YYYY-MM-DD' string, which breaks the 5m unix lookup.
        end_ts_5m = parsed_end
        if isinstance(end_ts_5m, str):
            try:
                dt = datetime.strptime(end_ts_5m, "%Y-%m-%d").replace(tzinfo=IST)
                end_ts_5m = int(dt.timestamp())
            except Exception:
                pass
        
        db_raw_5m = candle_db.get_candles(exchange, symbol, "5m", count=needed_5m, end_ts=end_ts_5m)
        resampled = resample_candles(db_raw_5m, timeframe)
        
        # If we successfully built ANY valid number of candles, serve them instantly!
        # Do not force a high minimum limit. This prevents hanging the TV WebSocket connection
        # if the 5m background thread is still actively downloading the 20,000 payload.
        if resampled and len(resampled) > 0: 
            final_resampled = resampled[-candles:] if len(resampled) > candles else resampled
            logger.info("Aggregation hit: mathematically built %d %s candles from %d 5m DB candles", 
                        len(final_resampled), timeframe, len(db_raw_5m))
            cd, vd = _format_candles_for_ui(final_resampled, timeframe)
            return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd}, exchange, symbol, timeframe, is_recent)
        else:
            logger.info("Aggregation fallback: Insufficient 5m candles (found %d) to build %s, fetching directly", 
                        len(db_raw_5m), timeframe)

    # ── Step 1: RAM cache check ───────────────────────────────────────────────
    stored = storage.get_candles(exchange, symbol, timeframe, count=candles, end_time=parsed_end)

    if is_recent and stored:
        last_fetch = storage.last_refresh.get(exchange, {}).get(symbol, {}).get(timeframe, 0.0)
        age        = time.time() - last_fetch
        if age < 12.0:   # serve from RAM as long as data is < 12 s old
            logger.info("Cache hit: serving %d candles (age=%.0fs)", len(stored), age)
            cd, vd = _format_candles_for_ui(stored, timeframe)
            return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd}, exchange, symbol, timeframe, is_recent)
        logger.info("Cache stale (%.0fs) — re-fetching from TradingView", age)

    # ── Step 2: DB check — serve from DB while fetching fresh data ───────────
    # If we have DB data but RAM is cold (e.g., just restarted), load it now
    if not stored and is_recent:
        db_candles = candle_db.get_candles(exchange, symbol, timeframe, count=candles)
        if db_candles:
            logger.info("Serving %d candles from SQLite (RAM was cold)", len(db_candles))
            cd, vd = _format_candles_for_ui(db_candles, timeframe)
            # Also push into RAM for next call
            _load_db_into_ram(exchange, symbol, timeframe)
            return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd}, exchange, symbol, timeframe, is_recent)

    # ── Step 3: Fetch from TradingView ───────────────────────────────────────
    # If a gap-fill is already running for this series, don't race with it
    series_key = (exchange, symbol, timeframe)
    if series_key in _gap_filling:
        logger.info("Gap-fill in progress for %s:%s [%s] — serving DB snapshot", exchange, symbol, timeframe)
        db_snap = candle_db.get_candles(exchange, symbol, timeframe, count=candles)
        if db_snap:
            cd, vd = _format_candles_for_ui(db_snap, timeframe)
            return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd}, exchange, symbol, timeframe, is_recent)
        return {"status": "loading", "candleData": [], "volumeData": [],
                "message": "Initial data fetch in progress — please wait"}

    # Always use the per-TF fetch limit; deep history comes from scroll-back
    fetch_limit = TF_FETCH_LIMIT.get(timeframe, 500)
    logger.info("Fetching from TradingView: %s:%s [%s] limit=%d", exchange, symbol, timeframe, fetch_limit)

    try:
        cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
        jwt_value    = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
        fetcher      = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
        raw_candles  = fetcher.fetch_historical_data(
            exchange   = exchange,
            symbol     = symbol,
            timeframe  = timeframe,
            limit      = fetch_limit,
            start_date = parsed_end,
            chunk_size = 5000 if fetch_limit > 5000 else fetch_limit,
            delay_ms   = 250,
        )
    except Exception as exc:
        logger.error("TV fetch failed: %s", exc)
        # Graceful fallback: serve whatever we have in DB rather than a 500
        fallback = candle_db.get_candles(exchange, symbol, timeframe, count=candles,
                                         end_ts=int(end_time) if end_time else None)
        if fallback:
            cd, vd = _format_candles_for_ui(fallback, timeframe)
            return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd, "warning": "Live fetch failed — serving cached data"}, exchange, symbol, timeframe, is_recent)
        raise HTTPException(500, f"Failed to fetch OHLC data: {exc}")

    if not raw_candles:
        fallback = candle_db.get_candles(exchange, symbol, timeframe, count=candles)
        if fallback:
            cd, vd = _format_candles_for_ui(fallback, timeframe)
            return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd}, exchange, symbol, timeframe, is_recent)
        return {"status": "success", "candleData": [], "volumeData": []}

    # Persist to SQLite + update RAM cache
    _seed_storage(exchange, symbol, timeframe, raw_candles, prepend=(end_time is not None))
    logger.info("Stored %d fresh candles for %s:%s [%s]", len(raw_candles), exchange, symbol, timeframe)

    final = storage.get_candles(exchange, symbol, timeframe, count=candles, end_time=parsed_end)
    cd, vd = _format_candles_for_ui(final, timeframe)
    return _sync_tick({"status": "success", "candleData": cd, "volumeData": vd}, exchange, symbol, timeframe, is_recent)


@app.get("/api/features")
def get_features(
    exchange:  str = Query("OANDA"),
    symbol:    str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    limit:     int = Query(50, ge=1, le=500),
):
    features = storage.get_features(exchange, symbol, timeframe, count=limit)
    return {"status": "success", "data": features}


@app.get("/api/indicators")
def get_indicators(
    exchange:   str = Query("OANDA"),
    symbol:     str = Query("EURUSD"),
    timeframe:  str = Query("1d"),
    indicators: str = Query("RSI,Stoch.K"),
):
    ind_list = [i.strip() for i in indicators.split(",") if i.strip()]
    logger.info("Indicators → %s:%s tf=%s inds=%s", exchange, symbol, timeframe, ind_list)
    try:
        result = Indicators().scrape(exchange=exchange, symbol=symbol,
                                     timeframe=timeframe, indicators=ind_list)
        return result
    except Exception as exc:
        logger.error("Indicator fetch failed: %s", exc)
        raise HTTPException(500, f"Failed to fetch indicators: {exc}")


@app.get("/api/watchlist")
def get_watchlist():
    results   = []
    ind_scraper = Indicators()
    for item in WATCHLIST_SYMBOLS:
        exchange, symbol = item["exchange"], item["symbol"]
        try:
            resp    = ind_scraper.scrape(exchange=exchange, symbol=symbol,
                                         timeframe="1d",
                                         indicators=["close", "open", "change", "Perf.W"])
            data    = resp.get("data", {})
            close   = data.get("close",  0)
            open_   = data.get("open",   close)
            change  = data.get("change", 0)
            perf_w  = data.get("Perf.W", 0)
            results.append({
                "exchange":  exchange, "symbol": symbol,
                "price":     round(close,  5),
                "open":      round(open_,  5),
                "change":    round(change, 5),
                "changePct": round(perf_w, 2),
                "isUp":      change >= 0,
            })
        except Exception as exc:
            logger.warning("Watchlist failed for %s:%s — %s", exchange, symbol, exc)
            results.append({"exchange": exchange, "symbol": symbol,
                            "price": 0, "open": 0, "change": 0, "changePct": 0,
                            "isUp": True, "error": str(exc)})

    return {"status": "success", "data": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)