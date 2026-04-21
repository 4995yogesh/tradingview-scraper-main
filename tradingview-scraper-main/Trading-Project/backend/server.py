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
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing as _mp

# ── Worker pool: use all logical CPU cores ────────────────────────────────────
_CPU_WORKERS: int = max(4, _mp.cpu_count())
from dotenv import load_dotenv

load_dotenv()

from typing import List, Optional
import pandas as pd
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# ── Package path setup ────────────────────────────────────────────────────────
ROOT    = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PIPE    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "project"))
sys.path.insert(0, ROOT)
sys.path.insert(0, PIPE)
sys.path.insert(0, PROJECT)   # exposes indicators/, api/, etc.


from tradingview_scraper.symbols.technicals import Indicators
from tradingview_scraper.symbols.historical import HistoricalFetcher
from pipeline.main import pipeline
from pipeline.data.storage import storage
from pipeline.data.db import candle_db          # ← SQLite layer
from indicators.consolidation import consolidation_boxes  # PROJECT path active now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)



# ── Feedback store (optional — degrades gracefully) ────────────────────────────
_feedback = None
try:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "data"))
    from ml_feedback import feedback_store as _feedback
    logger.info("MLFeedbackStore loaded — %s", _feedback.summary())
except Exception as _fb_err:
    logger.warning("MLFeedbackStore not available (%s)", _fb_err)

# ── Detection Scorer (optional — degrades gracefully if detection_model.pkl absent) ──
_detection_scorer = None
try:
    _DETECTION_TRAINER = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "project", "ml", "detection_trainer")
    )
    sys.path.insert(0, _DETECTION_TRAINER)
    from detection_scorer import get_detection_scorer as _get_detection_scorer
    _detection_scorer = _get_detection_scorer()
    logger.info("DetectionScorer loaded — ready=%s version=%s",
                _detection_scorer.ready, _detection_scorer.version)
except Exception as _det_err:
    logger.warning("DetectionScorer not available — model boxes disabled (%s)", _det_err)

# ── Constants ─────────────────────────────────────────────────────────────────

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w", "1M": "1M",
    "1D": "1d", "1W": "1w",
}

# Timeframes stored in SQLite via routine gap-fill (intra-day are derived from 5m)
PERSISTENT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

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

# ── Lightweight TTL cache for expensive aggregation endpoints ─────────────────
_cache_lock   = threading.Lock()
_cache_store: dict = {}   # key → (computed_at, result)

def _cache_get(key: str, ttl_s: float = 8.0):
    """Return cached value if fresh, else None."""
    with _cache_lock:
        entry = _cache_store.get(key)
        if entry and (time.time() - entry[0]) < ttl_s:
            return entry[1]
    return None

def _cache_set(key: str, value):
    with _cache_lock:
        _cache_store[key] = (time.time(), value)


# ── Per-box ML score cache (avoids re-inferring during consecutive polls) ─────
# Key  : (symbol, timeframe, time_start_ms, time_end_ms)
# Value: (recorded_at, {ml_score, ml_label, ml_confidence, ml_top_features, ...})
# TTL  : 300 s (box geometry never changes within a session)
_ml_score_cache: dict = {}
_ML_SCORE_TTL = 300.0  # seconds

# ── ML Scorer (optional — degrades gracefully if model.pkl absent) ────────────
_scorer = None
try:
    from ml.consolidation_scorer.scorer import ConsolidationScorer
    _scorer = ConsolidationScorer()
    if _scorer:
        logger.info("ConsolidationScorer v%s loaded — ready=%s", 
                    _scorer.VERSION if hasattr(_scorer, 'VERSION') else 'unknown',
                    _scorer.ready)
        if _scorer.ready:
            # Clear ML cache on startup to ensure new thresholds (v6) take effect
            _ml_score_cache.clear()
            logger.info("[ML] Score cache cleared for version alignment.")
            
            from ml.consolidation_scorer.features import EXPECTED_FEATURE_COUNT
            logger.info("[ML] Model expects %d features", len(_scorer._feature_cols))
            logger.info("[ML] Pipeline produces %d features", EXPECTED_FEATURE_COUNT)
except Exception as _scorer_err:
    logger.warning("ConsolidationScorer not available — ML fields will show neutral defaults (%s)", _scorer_err)

def _ml_cache_get(symbol: str, tf: str, ts: int, te: int) -> dict | None:
    """Return cached ML score dict for a box if still fresh, else None."""
    key = (symbol, tf, ts, te)
    with _cache_lock:
        entry = _ml_score_cache.get(key)
        if entry and (time.time() - entry[0]) < _ML_SCORE_TTL:
            return entry[1]
    return None

def _ml_cache_set(symbol: str, tf: str, ts: int, te: int, value: dict) -> None:
    key = (symbol, tf, ts, te)
    with _cache_lock:
        _ml_score_cache[key] = (time.time(), value)



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
        for candle in formatted:
            storage.append_candle(exchange, symbol, timeframe, candle)

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
    Detect and fill gaps in candle data.
    Always fetches a minimum STARTUP_BARS window to heal any internal gaps
    (e.g. overnight holes caused by periodic refresh only adding the latest
    few candles, making latest_ts look current while mid-range data is missing).
    Runs in a background thread — does not block server startup.
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

        # First-time (empty DB) — deep backfill
        FIRST_FETCH = {
            "1m": 2000, "5m": 20000, "15m": 8000, "1d": 5000, "1w": 2000,
        }

        # Minimum bars to (re-)fetch on every startup to heal internal gaps.
        # e.g. 1m × 5000 = 83 hrs — covers any overnight / weekend hole.
        STARTUP_MIN = {
            "1m": 5000, "5m": 2000, "15m": 1000, "30m": 1000,
            "1h": 500, "4h": 500, "1d": 500, "1w": 100,
        }

        if latest_ts is None:
            fetch_limit = FIRST_FETCH.get(timeframe, 1000)
            logger.info("[gap-fill] First backfill for %s:%s [%s] limit=%d",
                        exchange, symbol, timeframe, fetch_limit)
        else:
            gap_secs     = now_ts - latest_ts
            missing_bars = max(gap_secs // interval + 20, STARTUP_MIN.get(timeframe, 200))
            fetch_limit  = int(missing_bars)
            logger.info("[gap-fill] %s:%s [%s] gap=%ds → fetching %d bars (includes startup min)",
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
    Fetch the very latest candles from TradingView and merge them
    into SQLite + RAM cache.  The limit is computed dynamically from
    the actual gap between the newest DB candle and now, so overnight
    or downtime gaps are automatically healed on the next cycle.
    """
    key = (exchange, symbol, timeframe)
    with _gap_filling_lock:
        if key in _gap_filling:
            return   # gap-fill already running; skip
        _gap_filling.add(key)
    try:
        # ── Compute dynamic limit based on real gap from DB ───────────────
        interval  = TF_INTERVAL_SECS.get(timeframe, 60)
        latest_ts = candle_db.get_latest_ts(exchange, symbol, timeframe)
        if latest_ts is not None:
            gap_secs     = max(0, int(time.time()) - latest_ts)
            missing_bars = gap_secs // interval + 5   # +5 buffer
            dynamic_limit = max(limit, int(missing_bars))
        else:
            dynamic_limit = limit
        # Cap at 5000 bars to keep each periodic fetch fast but large enough to heal weekends
        dynamic_limit = min(dynamic_limit, 5000)

        if dynamic_limit > limit:
            logger.info("[periodic] %s:%s [%s] gap detected (%ds) → fetching %d bars",
                        exchange, symbol, timeframe,
                        int(time.time()) - (latest_ts or 0), dynamic_limit)

        cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
        jwt_value    = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
        fetcher      = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
        raw = fetcher.fetch_historical_data(
            exchange=exchange, symbol=symbol, timeframe=timeframe,
            limit=dynamic_limit, chunk_size=dynamic_limit, delay_ms=100,
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
                time.sleep(0.3)   # short pause — 6 TFs × 0.3 s = ~2 s total per cycle


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
    allow_credentials=False,   # Must be False when origins=["*"]
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


@app.get("/api/repair")
def repair_gaps():
    """
    Immediately trigger a full gap-fill for all persistent series.
    Use this to heal overnight/downtime gaps without restarting the server.
    Runs async in background — returns immediately.
    """
    t = threading.Thread(target=_run_all_gap_fills, name="manual-gap-fill", daemon=True)
    t.start()
    return {"status": "ok", "message": "Gap-fill triggered for all series"}


@app.get("/api/timeframes")
def get_timeframes():
    """Return list of timeframes for infinite canvas (5 fixed)."""
    return {"status": "ok", "timeframes": ["1m", "5m", "15m", "1h", "4h"]}


@app.get("/api/chart-data")
def get_chart_data(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    """Thin proxy to /api/ohlc — used by InfiniteCanvas per-timeframe fetch."""
    return get_ohlc(exchange=exchange, symbol=symbol, timeframe=timeframe, candles=candles, end_time=end_time)


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


@app.get("/api/consolidation")
def get_consolidation(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    """Return consolidation boxes for given series."""
    use_timestamp = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
    parsed_end = int(end_time) if end_time and use_timestamp else end_time
    stored = storage.get_candles(exchange, symbol, timeframe, count=candles, end_time=parsed_end)
    if not stored:
        raise HTTPException(404, "No candle data available for consolidation")
    df = pd.DataFrame(stored)
    if use_timestamp:
        df.set_index(pd.to_datetime(df["time"], unit='s'), inplace=True)
    else:
        df.set_index(pd.to_datetime(df["time"]).dt.date, inplace=True)
    boxes_df = consolidation_boxes(df)
    return {"status": "success", "boxes": boxes_df.to_dict(orient="records")}


@app.get("/consolidations")
def get_consolidations_all():
    """
    Aggregate consolidation zones across ALL persistent timeframes.
    Parallel: each TF computed concurrently across all CPU cores.
    TTL-cached for 8 s so repeated frontend polls are instant.
    Returns: { status:'ok', zones:[{timeframe, timeStart(ms), timeEnd(ms), priceHigh, priceLow}] }
    """
    cached = _cache_get("consolidations")
    if cached is not None:
        return cached

    def _compute_tf(exchange: str, symbol: str, tf: str) -> list:
        zones = []
        try:
            stored = storage.get_candles(exchange, symbol, tf, count=1000)
            if not stored or len(stored) < 5:
                return zones

            use_timestamp = tf in ["1m", "5m", "15m", "30m", "1h", "4h"]
            df = pd.DataFrame(stored)

            if use_timestamp:
                df.index = pd.to_datetime(df["time"], unit='s', utc=True)
            else:
                df.index = pd.to_datetime(df["time"])

            apply_time_filter = tf in ["1m", "5m", "15m", "30m", "1h"]
            boxes_df = consolidation_boxes(df, min_bars=5, use_time_filter=apply_time_filter)
            if boxes_df.empty:
                return zones

            # ── ML Scoring (additive layer — never changes box detection) ──────
            scored_df = boxes_df  # default: unscored
            scorer_active = _scorer is not None and _scorer.ready
            if scorer_active:
                try:
                    # include_features=True embeds top feature values for debug panel
                    scored_df = _scorer.score(
                        df, boxes_df,
                        timeframe=tf,
                        threshold=0.0,           # no threshold filter — show ALL boxes
                        include_features=True,
                    )
                except Exception as score_exc:
                    logger.warning("Scorer failed for %s [%s]: %s", symbol, tf, score_exc)
                    scored_df = boxes_df  # fallback to unscored

            df_len = len(df)
            idx    = df.index
            logger.info("[DEBUG] %s [%s]: %d boxes detected, scorer_active=%s",
                        symbol, tf, len(scored_df), scorer_active)
            # ── Pre-fetch ALL box labels in ONE query per TF ────────────────
            # (avoids 1 sqlite3.connect() per box which was causing 1-min delays)
            box_label_cache = {}
            if _feedback is not None:
                try:
                    # Build all box_ids first (lightweight — no DB yet)
                    tmp_ids = []
                    for _, row_tmp in scored_df.iterrows():
                        try:
                            si = int(row_tmp["start"]); ei = int(row_tmp["end"])
                            if si >= df_len or ei >= df_len: continue
                            ts_s = int(pd.Timestamp(idx[si]).timestamp() * 1000)
                            ts_e = int(pd.Timestamp(idx[ei]).timestamp() * 1000)
                            tmp_ids.append(_feedback.make_box_id(symbol, tf, ts_s, ts_e))
                        except Exception:
                            pass
                    if tmp_ids:
                        import sqlite3 as _sqlite3
                        placeholders = ",".join("?" * len(tmp_ids))
                        conn = _sqlite3.connect(str(_feedback._db_path), check_same_thread=False)
                        rows = conn.execute(
                            f"SELECT box_id, user_label, pattern_type, breakout_direction, structure_type "
                            f"FROM boxes WHERE box_id IN ({placeholders})", tmp_ids
                        ).fetchall()
                        conn.close()
                        box_label_cache = {r[0]: r[1:] for r in rows}
                except Exception:
                    pass

            for _, row in scored_df.iterrows():
                try:
                    si = int(row["start"])
                    ei = int(row["end"])
                    if si >= df_len or ei >= df_len:
                        continue
                    ts_start = int(pd.Timestamp(idx[si]).timestamp() * 1000)
                    ts_end   = int(pd.Timestamp(idx[ei]).timestamp() * 1000)

                    # ── Per-box ML score cache ─────────────────────────────
                    cached_ml = _ml_cache_get(symbol, tf, ts_start, ts_end)
                    if cached_ml:
                        ml_score        = cached_ml["ml_score"]
                        ml_label        = cached_ml["ml_label"]
                        ml_color        = cached_ml["ml_color"]
                        ml_confidence   = cached_ml["ml_confidence"]
                        ml_status       = cached_ml["ml_status"]
                        ml_top_features = cached_ml.get("ml_top_features", [])
                        ml_features     = cached_ml.get("ml_features", {})
                        lc              = cached_ml.get("lc", {
                            "border": "rgba(144,202,249,0.70)",
                            "fill":   "rgba(144,202,249,0.10)",
                        })
                    else:
                        ml_score      = float(row.get("quality", 0.5))
                        ml_label      = str(row.get("ml_label", "NEUTRAL"))
                        ml_color      = str(row.get("quality_color", "#FFB86C"))
                        ml_confidence = float(row.get("ml_confidence", 0.0))
                        ml_status     = str(row.get("ml_status",
                            "inactive" if not scorer_active else "active"))

                        lc = {
                            "GOOD":    {"border": "rgba(38,166,154,0.85)",  "fill": "rgba(38,166,154,0.12)"},
                            "BAD":     {"border": "rgba(239,83,80,0.85)",   "fill": "rgba(239,83,80,0.12)"},
                            "NEUTRAL": {"border": "rgba(144,202,249,0.70)", "fill": "rgba(144,202,249,0.10)"},
                        }.get(ml_label, {"border": "rgba(144,202,249,0.70)", "fill": "rgba(144,202,249,0.10)"})

                        raw_top = row.get("ml_top_features", None)
                        ml_top_features = raw_top if (raw_top and isinstance(raw_top, list)) else []

                        ml_features = {}
                        if "ml_features" in row and isinstance(row["ml_features"], dict):
                            rf = row["ml_features"]
                            ml_features = dict(
                                sorted(rf.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
                            )
                        
                        missing_feats = row.get("ml_missing_features", []) or []
                        ml_debug = {
                            "status": ml_status,
                            "missing_features": missing_feats,
                            "expected_features": 27,
                            "actual_features": 27 - len(missing_feats)
                        }

                        _ml_cache_set(symbol, tf, ts_start, ts_end, {
                            "ml_score":            ml_score,
                            "ml_label":            ml_label,
                            "ml_color":            ml_color,
                            "ml_confidence":       ml_confidence,
                            "ml_status":           ml_status,
                            "lc":                  lc,
                            "ml_top_features":     ml_top_features,
                            "ml_features":         ml_features,
                            "pattern_prediction":  str(row.get("pattern_prediction") or "") or None,
                            "pattern_confidence":  float(row.get("pattern_confidence") or 0.0),
                            "ml_debug":            ml_debug,
                        })

                    # ── Compute structural pattern suggestion ───────────
                    sug_res = {}
                    if _feedback is not None and hasattr(_feedback, "suggest_pattern_type"):
                        sug_res = _feedback.suggest_pattern_type(df, ei, float(row["top"]), float(row["bottom"])) or {}

                    zone = {
                        "timeframe":           tf,
                        "timeStart":           ts_start,
                        "timeEnd":             ts_end,
                        "priceHigh":           float(row["top"]),
                        "priceLow":            float(row["bottom"]),
                        "ml_score":            round(ml_score, 4),
                        "ml_label":            ml_label,
                        "ml_color":            ml_color,
                        "ml_confidence":       round(ml_confidence, 4),
                        "ml_status":           ml_status,
                        "ml_border":           lc["border"],
                        "ml_fill":             lc["fill"],
                        "ml_features":         ml_features,
                        "ml_top_features":     ml_top_features,
                        "pattern_suggestion":  sug_res.get("pattern_suggestion"),
                        "breakout_direction":  sug_res.get("breakout_direction"),
                        "structure_type":      sug_res.get("structure_type"),
                        "swing_count":         sug_res.get("swing_count", 0),
                        "pattern_prediction":  cached_ml.get("pattern_prediction") if cached_ml else (
                            str(row.get("pattern_prediction") or "") or None
                        ),
                        "pattern_confidence":  cached_ml.get("pattern_confidence", 0.0) if cached_ml else (
                            float(row.get("pattern_confidence") or 0.0)
                        ),
                        "ml_debug":            cached_ml.get("ml_debug", {}) if cached_ml else {},
                    }

                    # ── Attach box_id + user labels (from batch cache) ─────
                    if _feedback is not None:
                        box_id = _feedback.make_box_id(symbol, tf, ts_start, ts_end)
                        zone["box_id"] = box_id
                        db_row = box_label_cache.get(box_id)
                        zone["user_label"]        = db_row[0] if db_row else None
                        zone["pattern_type"]      = db_row[1] if db_row else None
                        zone["breakout_direction"] = zone["breakout_direction"] or (db_row[2] if db_row else None)
                        zone["structure_type"]     = zone["structure_type"]     or (db_row[3] if db_row else None)
                    else:
                        zone["box_id"]       = None
                        zone["user_label"]   = None
                        zone["pattern_type"] = None

                    zones.append(zone)

                    # ── Feedback loop: record box (fire-and-forget) ─────────
                    if _feedback is not None and ml_status == "active":
                        try:
                            zone_with_symbol = {
                                **zone, "symbol": symbol,
                                "swing_high_1": sug_res.get("swing_high_1"),
                                "swing_low_1":  sug_res.get("swing_low_1"),
                            }
                            _feedback.record_box(zone_with_symbol)
                        except Exception:
                            pass  # never block the response

                except Exception as inner_exc:
                    logger.warning("Zone parse error %s [%s] row=%s: %s", symbol, tf,
                                   getattr(row, 'name', '?'), inner_exc)
        except Exception as exc:
            logger.warning("Consolidation failed %s:%s [%s]: %s", exchange, symbol, tf, exc)
        return zones


    all_zones = []
    tasks = [
        (exchange, symbol, tf)
        for exchange, symbol in PERSISTENT_SYMBOLS
        for tf in PERSISTENT_TIMEFRAMES
    ]
    with ThreadPoolExecutor(max_workers=min(_CPU_WORKERS, len(tasks) or 1)) as pool:
        futures = {pool.submit(_compute_tf, ex, sym, tf): (ex, sym, tf) for ex, sym, tf in tasks}
        for fut in as_completed(futures):
            all_zones.extend(fut.result())

    result = {"status": "ok", "zones": all_zones}
    _cache_set("consolidations", result)
    return result


@app.get("/swings")
def get_swings_all():
    """
    3-bar pivot swing highs/lows with server-side 3+3 active unmitigated selection.
    Per TF: detects swings, checks directional mitigation, selects 3 closest above
    and 3 closest below current price. Returns active + mitigated swings.
    TTL-cached 8s. Returns: { status:'ok', swings:[{timeframe, type, price, time_ms, active, mitigated}] }
    """
    cached = _cache_get("swings")
    if cached is not None:
        return cached

    LOOKBACK = 300
    ACTIVE_COUNT = 3  # per side

    def _compute_swings(exchange: str, symbol: str, tf: str) -> list:
        result_swings = []
        try:
            db_rows = candle_db.get_candles(exchange, symbol, tf, count=2000)
            if not db_rows or len(db_rows) < 3:
                return result_swings

            rows_sorted = sorted(db_rows, key=lambda r: int(r["ts"]))
            ts_arr = [int(r["ts"])     for r in rows_sorted]
            hi_arr = [float(r["high"]) for r in rows_sorted]
            lo_arr = [float(r["low"])  for r in rows_sorted]
            cl_arr = [float(r["close"]) for r in rows_sorted]

            n       = len(ts_arr)
            start_i = max(1, n - LOOKBACK - 1)
            end_i   = n - 1

            # Step 1: detect pivots
            raw_swings = []  # {type, price, idx, time_ms}
            for i in range(start_i, end_i):
                if hi_arr[i] > hi_arr[i-1] and hi_arr[i] > hi_arr[i+1]:
                    raw_swings.append({"type": "high", "price": hi_arr[i], "idx": i, "time_ms": ts_arr[i] * 1000})
                if lo_arr[i] < lo_arr[i-1] and lo_arr[i] < lo_arr[i+1]:
                    raw_swings.append({"type": "low",  "price": lo_arr[i], "idx": i, "time_ms": ts_arr[i] * 1000})

            # Step 2: directional mitigation per swing
            for sw in raw_swings:
                i0 = sw["idx"]
                mitigated = False
                moved_away = False
                for j in range(i0 + 1, n):
                    if sw["type"] == "high":
                        if not moved_away and lo_arr[j] < sw["price"]:
                            moved_away = True
                        if moved_away and hi_arr[j] >= sw["price"]:
                            mitigated = True
                            break
                    else:
                        if not moved_away and hi_arr[j] > sw["price"]:
                            moved_away = True
                        if moved_away and lo_arr[j] <= sw["price"]:
                            mitigated = True
                            break
                sw["mitigated"] = mitigated

            # Step 3: current price = last candle close
            current_price = cl_arr[-1]

            # Step 4: 3+3 selection from unmitigated
            unmitigated = [s for s in raw_swings if not s["mitigated"]]
            above = sorted([s for s in unmitigated if s["price"] > current_price],
                           key=lambda s: abs(s["price"] - current_price))
            below = sorted([s for s in unmitigated if s["price"] <= current_price],
                           key=lambda s: abs(s["price"] - current_price))

            active_set = set(id(s) for s in above[:ACTIVE_COUNT]) | set(id(s) for s in below[:ACTIVE_COUNT])

            # Most recent mitigated swings (for optional UI display), capped to avoid clutter
            mitigated_swings = sorted(
                [s for s in raw_swings if s["mitigated"]],
                key=lambda s: s["idx"], reverse=True
            )[:ACTIVE_COUNT * 2]  # max 6 most recent mitigated

            # Step 5: emit all unmitigated (active or inactive) + recent mitigated
            for sw in raw_swings:
                if not sw["mitigated"]:
                    result_swings.append({
                        "timeframe": tf, "type": sw["type"],
                        "price": sw["price"], "time_ms": sw["time_ms"],
                        "mitigated": False, "active": id(sw) in active_set,
                    })

            for sw in mitigated_swings:
                result_swings.append({
                    "timeframe": tf, "type": sw["type"],
                    "price": sw["price"], "time_ms": sw["time_ms"],
                    "mitigated": True, "active": False,
                })

        except Exception as exc:
            logger.warning("Swings failed %s:%s [%s]: %s", exchange, symbol, tf, exc)
        return result_swings

    all_swings = []
    tasks = [
        (exchange, symbol, tf)
        for exchange, symbol in PERSISTENT_SYMBOLS
        for tf in PERSISTENT_TIMEFRAMES
    ]
    with ThreadPoolExecutor(max_workers=min(_CPU_WORKERS, len(tasks) or 1)) as pool:
        futures = {pool.submit(_compute_swings, ex, sym, tf): (ex, sym, tf) for ex, sym, tf in tasks}
        for fut in as_completed(futures):
            all_swings.extend(fut.result())

    result = {"status": "ok", "swings": all_swings}
    _cache_set("swings", result)
    return result


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
async def get_watchlist():
    """
    Async watchlist — runs blocking Indicators.scrape() in a thread pool
    so it never blocks the uvicorn event loop.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_one(item: dict) -> dict:
        exchange, symbol = item["exchange"], item["symbol"]
        try:
            resp   = Indicators().scrape(
                exchange=exchange, symbol=symbol, timeframe="1d",
                indicators=["close", "open", "change", "Perf.W"],
            )
            data   = resp.get("data", {})
            close  = data.get("close",  0)
            open_  = data.get("open",   close)
            change = data.get("change", 0)
            perf_w = data.get("Perf.W", 0)
            return {
                "exchange": exchange, "symbol": symbol,
                "price":    round(close,  5),
                "open":     round(open_,  5),
                "change":   round(change, 5),
                "changePct":round(perf_w, 2),
                "isUp":     change >= 0,
            }
        except Exception as exc:
            logger.warning("Watchlist failed for %s:%s — %s", exchange, symbol, exc)
            return {
                "exchange": exchange, "symbol": symbol,
                "price": 0, "open": 0, "change": 0, "changePct": 0,
                "isUp": True, "error": str(exc),
            }

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=len(WATCHLIST_SYMBOLS) or 1) as pool:
        tasks   = [loop.run_in_executor(pool, _fetch_one, item) for item in WATCHLIST_SYMBOLS]
        results = await asyncio.gather(*tasks)

    return {"status": "success", "data": list(results)}


@app.get("/api/ml/meta")
def get_ml_meta():
    """
    Returns ML scorer metadata: version, feature list, thresholds, trained_on,
    contribs_ready flag, and feedback store summary.
    """
    ml_info = {"ready": False, "reason": "scorer not imported"}
    if _scorer is not None:
        ml_info = _scorer.meta()

    feedback_info = {}
    if _feedback is not None:
        try:
            feedback_info = _feedback.summary()
        except Exception:
            feedback_info = {"error": "summary unavailable"}

    return {"status": "ok", "ml": ml_info, "feedback": feedback_info}


@app.get("/api/ml/stats")
async def get_ml_stats():
    """
    Returns unified dataset statistics.
    Reuses structural labeling logic from train.py.
    Cached for 60 seconds (TASK 7).
    """
    global _ml_stats_cache, _ml_stats_last_update
    
    now = time.time()
    if _ml_stats_cache and (now - _ml_stats_last_update < ML_STATS_CACHE_TTL):
        return _ml_stats_cache

    try:
        # PROJECT variable at top already points to 'project'
        import sys as _sys
        _SCORER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "project", "ml", "consolidation_scorer"))
        if _SCORER_DIR not in _sys.path:
            _sys.path.insert(0, _SCORER_DIR)
        
        from train import prepare_unified_dataset
        
        # Consistent paths for the trainer
        _BACKEND_DATA = os.path.join(os.path.dirname(__file__), "data")
        _CANDLE_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "candles.db"))
        _FB_DB     = os.path.join(_BACKEND_DATA, "ml_feedback.db")

        combined = prepare_unified_dataset(db_path=_CANDLE_DB, fb_db_path=_FB_DB)
        
        if combined.empty:
            stats = {
                "total_samples": 0,
                "usable_samples": 0,
                "positives": 0,
                "negatives": 0,
                "ignored": 0
            }
        else:
            stats = {
                "total_samples": len(combined), 
                "usable_samples": int(combined["quality"].notna().sum()),
                "positives": int((combined["quality"] == 1).sum()),
                "negatives": int((combined["quality"] == 0).sum()),
                "ignored": int(combined["quality"].isna().sum())
            }
        
        _ml_stats_cache = stats
        _ml_stats_last_update = now
        return stats
    except Exception as e:
        logger.error("Failed to compute ML stats: %s", e)
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# User feedback endpoints
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel

class _UserFeedbackBody(_BaseModel):
    box_id:     str
    user_label: str   # GOOD | BAD | NEUTRAL
    timeframe:  str | None = None


@app.post("/api/ml/feedback/user")
def post_user_feedback(body: _UserFeedbackBody):
    """
    Store a human rating for a consolidation box.
    Upserts: creates a minimal row if box_id not yet in DB.
    Returns 200 on success.
    """
    import sqlite3 as _sq3

    valid = {"GOOD", "BAD", "NEUTRAL"}
    label = (body.user_label or "").strip().upper()
    if label not in valid:
        return {"status": "error", "reason": f"user_label must be one of {valid}"}

    _db_p = os.path.join(os.path.dirname(__file__), "data", "ml_feedback.db")
    try:
        conn = _sq3.connect(_db_p)
        conn.execute("PRAGMA journal_mode=WAL")

        # Try update first (fast path — box already recorded by ML scorer)
        cur = conn.execute(
            "UPDATE boxes SET user_label = ?, timeframe = COALESCE(nullif(timeframe,'unknown'), ?), updated_at = datetime('now') WHERE box_id = ?",
            (label, body.timeframe or 'unknown', body.box_id),
        )
        conn.commit()

        if cur.rowcount == 0:
            # Box not in DB — insert minimal row so label is persisted immediately
            conn.execute("""
                INSERT OR IGNORE INTO boxes
                    (box_id, symbol, timeframe, time_start, time_end,
                     price_high, price_low, ml_score, ml_label, ml_confidence,
                     ml_top_features, recorded_at, user_label, updated_at)
                VALUES (?, 'EURUSD', ?, 0, 0,
                        0.0, 0.0, 0.5, 'NEUTRAL', 0.0,
                        '[]', datetime('now'), ?, datetime('now'))
            """, (body.box_id, body.timeframe or 'unknown', label))
            conn.commit()
            logger.info("User feedback (inserted): box %s -> %s", body.box_id, label)
        else:
            logger.info("User feedback (updated): box %s -> %s", body.box_id, label)

        conn.close()
    except Exception as exc:
        logger.warning("post_user_feedback failed: %s", exc)
        return {"status": "error", "reason": str(exc)}

    # Keep in-memory feedback store in sync if available
    if _feedback is not None:
        _feedback.update_user_feedback(body.box_id, label)

    # Auto-retrain after each 100 newly labeled (unconsumed) samples globally.
    fresh_unconsumed = 0
    try:
        conn = _sq3.connect(_db_p)
        fresh_unconsumed = conn.execute(
            "SELECT COUNT(*) FROM boxes WHERE user_label IS NOT NULL AND (is_consumed = 0 OR is_consumed IS NULL)"
        ).fetchone()[0]
        conn.close()
    except Exception:
        fresh_unconsumed = 0

    auto_retrain_triggered = False
    if fresh_unconsumed >= _ML_RETRAIN_LABEL_BATCH and _ml_retrain_lock.is_set():
        _bg_ml_retrain()
        auto_retrain_triggered = True

    return {
        "status": "ok",
        "box_id": body.box_id,
        "user_label": label,
        "fresh_unconsumed_labels": fresh_unconsumed,
        "auto_retrain_batch": _ML_RETRAIN_LABEL_BATCH,
        "auto_retrain_triggered": auto_retrain_triggered,
    }

import time as _time_mod

# Stage definitions — matched against log messages from train.py
_ML_STAGES = [
    {"id": "init",     "label": "Initialising",              "pct": 5,  "keywords": ["Discovering available", "Training on"]},
    {"id": "load",     "label": "Loading OHLC data",         "pct": 15, "keywords": ["load_ohlc_from_db", "Processing"]},
    {"id": "detect",   "label": "Detecting boxes",           "pct": 30, "keywords": ["Detecting consolidation", "Detected "]},
    {"id": "features", "label": "Extracting features",       "pct": 45, "keywords": ["Extracting features", "Feature matrix"]},
    {"id": "labels",   "label": "Computing labels",          "pct": 58, "keywords": ["Computing auto-labels", "Human labels loaded", "Human label overrides"]},
    {"id": "train",    "label": "Training XGBoost model",    "pct": 72, "keywords": ["Training XGBoost quality model", "Train:", "Best iteration"]},
    {"id": "eval",     "label": "Evaluating & calibrating",  "pct": 85, "keywords": ["TEST RESULTS", "Threshold", "Bucket analysis"]},
    {"id": "pattern",  "label": "Pattern classifier",        "pct": 92, "keywords": ["Training pattern classifier", "Pattern model saved"]},
    {"id": "save",     "label": "Saving model",              "pct": 97, "keywords": ["Quality model saved", "model saved"]},
]

_ml_progress: dict = {
    "state":      "idle",       # idle | training | trained | error
    "stage":      None,
    "stage_label": None,
    "pct":        0,
    "logs":       [],           # list of {ts, msg} dicts, max 200
    "started_at": None,
    "finished_at": None,
    "elapsed_s":  None,
    "metrics":    {},           # MAE, pearson_r, threshold etc from result
    "error":      None,
}
_ml_retrain_lock = threading.Event()
_ml_retrain_lock.set()   # available
_ml_progress_lock = threading.Lock()
_ML_RETRAIN_LABEL_BATCH = 100

# ── ML Stats Cache (TASK 7) ──────────────────────────────────────────────────
_ml_stats_cache: dict = None
_ml_stats_last_update: float = 0
ML_STATS_CACHE_TTL = 60  # seconds


def _ml_log(msg: str, pct: int | None = None):
    """Append a log line and optionally update stage percentage."""
    global _ml_progress
    ts = _time_mod.strftime("%H:%M:%S")
    with _ml_progress_lock:
        _ml_progress["logs"].append({"ts": ts, "msg": msg})
        if len(_ml_progress["logs"]) > 300:
            _ml_progress["logs"] = _ml_progress["logs"][-300:]
        if pct is not None and pct > _ml_progress["pct"]:
            _ml_progress["pct"] = pct
        # Auto-detect stage from message
        for stage in _ML_STAGES:
            if any(kw in msg for kw in stage["keywords"]):
                if _ml_progress["pct"] <= stage["pct"]:
                    _ml_progress["pct"]         = stage["pct"]
                    _ml_progress["stage"]       = stage["id"]
                    _ml_progress["stage_label"] = stage["label"]
                break


class _MLLogHandler(logging.Handler):
    """Logging handler that pipes train.py output into _ml_progress['logs']."""
    def emit(self, record):
        try:
            msg = self.format(record)
            _ml_log(msg)
        except Exception:
            pass


def _bg_ml_retrain():
    """Fire-and-forget consolidation scorer retrain in background thread."""
    global _ml_progress
    if not _ml_retrain_lock.is_set():
        logger.info("ML retrain already running — skipping duplicate trigger")
        return
    _ml_retrain_lock.clear()
    with _ml_progress_lock:
        _ml_progress.update({
            "state": "training", "stage": "init", "stage_label": "Initialising",
            "pct": 2, "logs": [], "started_at": _time_mod.time(),
            "finished_at": None, "elapsed_s": None,
            "metrics": {}, "error": None,
        })

    def _run():
        global _ml_progress
        _ml_log("▶ ML Scorer retrain started", pct=2)
        # Attach log handler to root + train logger so all train.py output is captured
        _handler = _MLLogHandler()
        _handler.setFormatter(logging.Formatter("%(message)s"))
        _handler.setLevel(logging.DEBUG)
        _root_logger = logging.getLogger()
        _train_logger = logging.getLogger("train")
        _root_logger.addHandler(_handler)
        _train_logger.addHandler(_handler)
        try:
            import sys as _sys
            _SCORER_DIR = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "project", "ml", "consolidation_scorer")
            )
            _BACKEND_DATA = os.path.join(os.path.dirname(__file__), "data")
            _CANDLE_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "candles.db"))
            _FB_DB     = os.path.join(_BACKEND_DATA, "ml_feedback.db")
            _sys.path.insert(0, _SCORER_DIR)
            _ml_log("→ Loading train module…", pct=5)
            import importlib
            if "train" in _sys.modules:
                importlib.reload(_sys.modules["train"])
            from train import run_pipeline
            _ml_log("→ Starting pipeline…", pct=8)
            result = run_pipeline(
                db_path=_CANDLE_DB,
                fb_db_path=_FB_DB,
                train_all_series=True,
                max_candles_per_series=5000,
            )
            cnt = 0
            try:
                import sqlite3 as _sq3r
                _c = _sq3r.connect(_FB_DB)
                _c.execute("UPDATE boxes SET is_consumed = 1 WHERE user_label IS NOT NULL AND (is_consumed = 0 OR is_consumed IS NULL)")
                _c.commit()
                cnt = _c.execute("SELECT COUNT(*) FROM boxes WHERE user_label IS NOT NULL AND is_consumed = 1").fetchone()[0]
                _c.close()
            except Exception as _e:
                logger.warning("Failed to mark labels as consumed: %s", _e)
            # Extract metrics from result dict
            metrics = {}
            if result and isinstance(result, dict):
                metrics = {
                    "mae":               round(result.get("mae", 0), 4),
                    "pearson_r":         round(result.get("pearson_r", 0), 4),
                    "spearman_r":        round(result.get("spearman_r", 0), 4),
                    "optimal_threshold": round(result.get("optimal_threshold", 0.5), 3),
                    "train_rows":        result.get("train_rows", 0),
                    "test_rows":         result.get("test_rows", 0),
                    "human_label_count": result.get("human_label_count", 0),
                    "has_pattern_model": result.get("has_pattern_model", False),
                    "version":           result.get("version", ""),
                }
            elapsed = round(_time_mod.time() - _ml_progress["started_at"], 1)
            _ml_log(f"✓ Training complete in {elapsed}s | human_labels={cnt} | MAE={metrics.get('mae','?')}", pct=100)
            with _ml_progress_lock:
                _ml_progress["state"]       = "trained"
                _ml_progress["stage"]       = "save"
                _ml_progress["stage_label"] = "Complete"
                _ml_progress["pct"]         = 100
                _ml_progress["finished_at"] = _time_mod.time()
                _ml_progress["elapsed_s"]   = elapsed
                _ml_progress["label_count"] = cnt
                _ml_progress["metrics"]     = metrics
            logger.info("ML scorer retrain complete (labels=%d)", cnt)
            # Reload scorer weights
            if _scorer is not None:
                try:
                    _scorer.reload()
                    _ml_log("→ ConsolidationScorer weights reloaded")
                    logger.info("ConsolidationScorer reloaded after retrain")
                except Exception as re:
                    logger.warning("Scorer reload failed: %s", re)
        except Exception as e:
            elapsed = round(_time_mod.time() - (_ml_progress.get("started_at") or _time_mod.time()), 1)
            _ml_log(f"✗ Error: {e}", pct=None)
            with _ml_progress_lock:
                _ml_progress["state"]       = "error"
                _ml_progress["stage"]       = "error"
                _ml_progress["stage_label"] = "Error"
                _ml_progress["finished_at"] = _time_mod.time()
                _ml_progress["elapsed_s"]   = elapsed
                _ml_progress["error"]       = str(e)
            logger.error("ML scorer retrain failed: %s", e)
        finally:
            _root_logger.removeHandler(_handler)
            _train_logger.removeHandler(_handler)
            _ml_retrain_lock.set()

    threading.Thread(target=_run, daemon=True, name="ml-scorer-retrain").start()


@app.post("/api/ml/retrain")
def trigger_ml_retrain():
    """Manually trigger consolidation scorer retraining using GOOD/BAD/NEUTRAL labels."""
    if not _ml_retrain_lock.is_set():
        return {"status": "already_running", "reason": "Retrain already in progress"}

    cnt = 0
    try:
        import sqlite3 as _sq3
        _db_p = os.path.join(os.path.dirname(__file__), "data", "ml_feedback.db")
        _c = _sq3.connect(_db_p)
        cnt = _c.execute("SELECT COUNT(*) FROM boxes WHERE user_label IS NOT NULL AND (is_consumed = 0 OR is_consumed IS NULL)").fetchone()[0]
        _c.close()
    except Exception:
        pass

    if cnt < _ML_RETRAIN_LABEL_BATCH:
        return {"status": "insufficient_data",
                "labeled_count": cnt,
                "reason": f"Need at least {_ML_RETRAIN_LABEL_BATCH} GOOD/BAD/NEUTRAL labels. Have {cnt}."}

    _bg_ml_retrain()
    return {"status": "queued", "labeled_count": cnt,
            "message": "Consolidation scorer retraining in background"}


@app.get("/api/ml/train-status")
def get_ml_train_status():
    """Return current training state (compact, for toolbar badge)."""
    with _ml_progress_lock:
        return {
            "status":          "ok",
            "state":           _ml_progress["state"],
            "retrain_running": not _ml_retrain_lock.is_set(),
            "pct":             _ml_progress["pct"],
            "stage_label":     _ml_progress["stage_label"],
            "elapsed_s":       _ml_progress["elapsed_s"],
            "label_count":     _ml_progress["label_count"],
            "error":           _ml_progress["error"],
        }


@app.get("/api/ml/train-progress")
def get_ml_train_progress():
    """Return full training progress: stages, logs, metrics."""
    with _ml_progress_lock:
        data = dict(_ml_progress)
    data["retrain_running"] = not _ml_retrain_lock.is_set()
    data["status"] = "ok"
    return data



@app.get("/api/ml/labeled-list")
def get_labeled_list():
    """Return all GOOD/BAD/NEUTRAL labeled boxes, newest first."""
    if _feedback is None:
        return {"status": "error", "items": [], "total": 0}
    items = _feedback.get_labeled_list()
    return {"status": "ok", "items": items, "total": len(items)}


@app.get("/api/ml/active-learning-queue")
def get_active_learning_queue(limit: int = Query(10, ge=1, le=50)):
    """
    Return the most uncertain unlabeled boxes for human annotation.
    Uncertainty proxy: lowest ml_confidence first.
    """
    import sqlite3 as _sq3

    _db_p = os.path.join(os.path.dirname(__file__), "data", "ml_feedback.db")
    try:
        conn = _sq3.connect(_db_p)
        conn.row_factory = _sq3.Row
        rows = conn.execute(
            """
            SELECT box_id, symbol, timeframe, time_start, time_end,
                   price_high, price_low, ml_label, ml_confidence, ml_score
            FROM boxes
            WHERE user_label IS NULL
            ORDER BY COALESCE(ml_confidence, 1.0) ASC, time_end DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
    except Exception as exc:
        return {"status": "error", "reason": str(exc), "items": [], "total": 0}

    items = [dict(r) for r in rows]
    return {"status": "ok", "items": items, "total": len(items), "limit": limit}


# ─────────────────────────────────────────────────────────────────────────────
# Detection system endpoints (human-in-the-loop improvement)
# ─────────────────────────────────────────────────────────────────────────────

class _DetectionFeedbackBody(_BaseModel):
    box_id:           str
    detection_label:  str   # RIGHT | WRONG | IGNORE


@app.post("/api/detection/feedback")
def post_detection_feedback(body: _DetectionFeedbackBody):
    """
    Store RIGHT / WRONG / IGNORE detection label for a box.
    Box must already exist in DB (auto-created at inference time).
    """
    if _feedback is None:
        return {"status": "error", "reason": "feedback store not initialised"}

    valid = {"RIGHT", "WRONG", "IGNORE"}
    label = (body.detection_label or "").strip().upper()
    if label not in valid:
        return {"status": "error", "reason": f"detection_label must be one of {valid}"}

    ok = _feedback.update_detection_label(body.box_id, label)
    if not ok:
        return {"status": "not_found",
                "reason": f"box_id {body.box_id!r} not in DB — must be scored first"}

    logger.info("Detection feedback: box %s → %s", body.box_id, label)


    return {"status": "ok", "box_id": body.box_id, "detection_label": label}


class _ManualBoxBody(_BaseModel):
    symbol:    str
    timeframe: str
    timeStart: int   # unix ms
    timeEnd:   int   # unix ms
    priceHigh: float
    priceLow:  float


@app.post("/api/detection/manual_box")
def post_manual_box(body: _ManualBoxBody):
    """
    Save a user-drawn consolidation box.
    Stored with detection_label=RIGHT, source=manual (highest training weight).
    """
    if _feedback is None:
        return {"status": "error", "reason": "feedback store not initialised"}

    zone = body.model_dump()
    box_id = _feedback.insert_manual_box(zone)
    if box_id is None:
        return {"status": "error", "reason": "insert_manual_box failed"}

    # Invalidate consolidation cache so new box is visible immediately
    _cache_set("consolidations", None)
    logger.info("Manual box saved: %s [%s %s %.5f–%.5f]",
                box_id, body.symbol, body.timeframe, body.priceLow, body.priceHigh)
    return {"status": "ok", "box_id": box_id, "source": "manual"}


# ── Background retrain helper ─────────────────────────────────────────────────
_retrain_lock_flag = threading.Event()
_retrain_lock_flag.set()  # starts as "available"


def _bg_retrain():
    """Fire-and-forget retrain in background thread."""
    if not _retrain_lock_flag.is_set():
        logger.info("Retrain already in progress — skipping duplicate trigger")
        return
    _retrain_lock_flag.clear()

    def _run():
        try:
            from detection_train import run_detection_training
            result = run_detection_training(min_samples=10)
            logger.info("Background retrain complete: %s", result.get("status"))
            # Reload scorer weights after training
            if _detection_scorer is not None:
                _detection_scorer.reload()
        except Exception as e:
            logger.error("Background retrain failed: %s", e)
        finally:
            _retrain_lock_flag.set()

    threading.Thread(target=_run, daemon=True, name="detection-retrain").start()


@app.post("/api/detection/retrain")
def trigger_retrain():
    """
    Manually trigger detection model retraining.
    Returns immediately; training runs in background.
    """
    if not _retrain_lock_flag.is_set():
        return {"status": "already_running",
                "reason": "A retrain job is already in progress — please wait"}

    # Count labeled samples
    labeled_count = 0
    try:
        import sqlite3 as _sq3
        _db_p = os.path.join(os.path.dirname(__file__), "data", "ml_feedback.db")
        _c = _sq3.connect(_db_p)
        labeled_count = _c.execute(
            "SELECT COUNT(*) FROM boxes WHERE detection_label IN ('RIGHT','WRONG')"
        ).fetchone()[0]
        _c.close()
    except Exception:
        pass

    if labeled_count < 10:
        return {
            "status": "insufficient_data",
            "labeled_count": labeled_count,
            "reason": f"Need at least 10 labeled boxes (RIGHT/WRONG). Have {labeled_count}.",
        }

    _bg_retrain()
    return {
        "status": "queued",
        "labeled_count": labeled_count,
        "message": "Retraining in background — reload model_boxes in ~30s",
    }


@app.get("/api/detection/stats")
def get_detection_stats():
    """
    Return labeled box counts so the frontend can show a training progress counter.
    """
    MIN_MANUAL  = 10   # minimum to manually trigger retrain
    AUTO_TARGET = 20   # threshold for auto-retrain
    try:
        import sqlite3 as _sq3
        _db_p = os.path.join(os.path.dirname(__file__), "data", "ml_feedback.db")
        _c = _sq3.connect(_db_p)
        right_count  = _c.execute("SELECT COUNT(*) FROM boxes WHERE detection_label='RIGHT'").fetchone()[0]
        wrong_count  = _c.execute("SELECT COUNT(*) FROM boxes WHERE detection_label='WRONG'").fetchone()[0]
        ignore_count = _c.execute("SELECT COUNT(*) FROM boxes WHERE detection_label='IGNORE'").fetchone()[0]
        _c.close()
    except Exception:
        right_count = wrong_count = ignore_count = 0

    labeled = right_count + wrong_count
    model_ready = _detection_scorer is not None and _detection_scorer.ready
    retrain_running = not _retrain_lock_flag.is_set()

    return {
        "status": "ok",
        "labeled":        labeled,
        "right":          right_count,
        "wrong":          wrong_count,
        "ignore":         ignore_count,
        "min_to_train":   MIN_MANUAL,
        "auto_target":    AUTO_TARGET,
        "need_more":      max(0, MIN_MANUAL - labeled),
        "to_auto":        max(0, AUTO_TARGET - labeled),
        "model_ready":    model_ready,
        "retrain_running": retrain_running,
    }


@app.get("/api/detection/model_boxes")
def get_model_boxes(
    symbol:    str = Query("EURUSD"),
    timeframe: str = Query("1h"),
    candles:   int = Query(500, ge=50, le=5000),
    threshold: float = Query(0.5, ge=0.0, le=1.0),
):
    """
    Generate candidate consolidation boxes using the detection model.
    Applies NMS to de-duplicate overlapping candidates.
    Returns boxes colour-coded by confidence:
      - detection_label = 'valid'     → high confidence (green)
      - detection_label = 'uncertain' → score 0.45–0.55  (yellow, dashed)
      - detection_label = 'invalid'   → filtered out (not returned)
    """
    if _detection_scorer is None or not _detection_scorer.ready:
        return {
            "status": "model_not_ready",
            "reason": "Detection model not trained yet — label boxes and retrain first",
            "boxes": [],
        }

    # Get candle data
    try:
        stored = storage.get_candles("OANDA", symbol, timeframe, count=candles)
        if not stored or len(stored) < 50:
            return {"status": "ok", "boxes": [], "reason": "insufficient candle data"}

        use_ts = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
        df = pd.DataFrame(stored)
        if use_ts:
            df.index = pd.to_datetime(df["time"], unit="s", utc=True)
        else:
            df.index = pd.to_datetime(df["time"])

    except Exception as e:
        logger.warning("get_model_boxes: candle fetch failed: %s", e)
        return {"status": "error", "reason": str(e), "boxes": []}

    # Generate candidates
    try:
        from candidate_generator import generate_candidates, nms
        candidates = generate_candidates(df)
    except Exception as e:
        logger.warning("get_model_boxes: candidate generation failed: %s", e)
        return {"status": "error", "reason": str(e), "boxes": []}

    # Score candidates
    try:
        from detection_features import extract_detection_features
        scored = _detection_scorer.score_candidates(df, candidates,
                                                    extract_fn=extract_detection_features)
    except Exception as e:
        logger.warning("get_model_boxes: scoring failed: %s", e)
        return {"status": "error", "reason": str(e), "boxes": []}

    # NMS de-duplication
    try:
        from candidate_generator import nms
        scored = nms(scored, score_key="detection_score")
    except Exception:
        pass

    # Filter: keep valid + uncertain; drop invalid and unscored
    use_threshold = threshold if threshold != 0.5 else (_detection_scorer.threshold or 0.5)
    visible = [
        c for c in scored
        if c.get("detection_label") in ("valid", "uncertain")
        and c.get("detection_score") is not None
        and c.get("detection_score", 0) >= 0.4  # minimum floor
    ]

    # Convert to frontend format
    idx = df.index
    result_boxes = []
    for c in visible:
        try:
            si, ei = int(c["start"]), int(c["end"])
            ts_start = int(pd.Timestamp(idx[si]).timestamp() * 1000)
            ts_end   = int(pd.Timestamp(idx[ei]).timestamp() * 1000)
            score    = round(float(c["detection_score"]), 4)
            result_boxes.append({
                "timeframe":        timeframe,
                "timeStart":        ts_start,
                "timeEnd":          ts_end,
                "priceHigh":        round(float(c["price_high"]), 6),
                "priceLow":         round(float(c["price_low"]),  6),
                "detection_score":  score,
                "detection_label":  c["detection_label"],
                "source":           "model",
                "model_version":    _detection_scorer.version,
                # Frontend color hints
                "ml_border": "rgba(38,166,154,0.85)"   if score >= 0.65 else "rgba(255,184,0,0.85)",
                "ml_fill":   "rgba(38,166,154,0.10)"   if score >= 0.65 else "rgba(255,184,0,0.08)",
                "is_uncertain": c["detection_label"] == "uncertain",
            })
        except Exception:
            continue

    logger.info("model_boxes: %s [%s] → %d candidates → %d visible",
                symbol, timeframe, len(scored), len(result_boxes))
    return {
        "status": "ok",
        "boxes":  result_boxes,
        "model_version": _detection_scorer.version,
        "threshold_used": use_threshold,
        "total_candidates": len(scored),
    }


@app.get("/api/detection/stats")
def get_detection_stats():
    """Return labeled count, model version, threshold, and accuracy metrics."""
    MIN_MANUAL  = 10
    AUTO_TARGET = 20
    labeled_count = 0
    right_count = wrong_count = ignore_count = manual_count = 0
    user_labeled = 0   # GOOD / BAD / NEUTRAL ML quality labels
    try:
        import sqlite3 as _sq3
        _db_p = os.path.join(os.path.dirname(__file__), "data", "ml_feedback.db")
        _c = _sq3.connect(_db_p)
        rows = _c.execute("""
            SELECT detection_label, source, COUNT(*) as n
            FROM boxes
            WHERE detection_label IS NOT NULL
            GROUP BY detection_label, source
        """).fetchall()
        # Count ML quality labels (GOOD/BAD/NEUTRAL) separately
        try:
            user_labeled = _c.execute(
                "SELECT COUNT(*) FROM boxes WHERE user_label IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            user_labeled = 0
        _c.close()
        for label, src, n in rows:
            labeled_count += n
            if label == "RIGHT":
                right_count += n
                if src == "manual":
                    manual_count += n
            elif label == "WRONG":
                wrong_count += n
            elif label == "IGNORE":
                ignore_count += n
    except Exception:
        pass

    # Total for toolbar counter = detection labels + ML quality labels
    total_labeled = labeled_count + user_labeled
    model_ready = _detection_scorer is not None and _detection_scorer.ready

    model_meta = {}
    if _detection_scorer is not None:
        model_meta = _detection_scorer.meta()

    return {
        "status":          "ok",
        # ── Fields the toolbar reads ──
        "labeled":         total_labeled,
        "user_labeled":    user_labeled,
        "detection_labeled": labeled_count,
        "min_to_train":    MIN_MANUAL,
        "auto_target":     AUTO_TARGET,
        "model_ready":     model_ready,
        "need_more":       max(0, MIN_MANUAL - total_labeled),
        "to_auto":         max(0, AUTO_TARGET - total_labeled),
        # ── Detection breakdown ──
        "labeled_count":   labeled_count,
        "right_count":     right_count,
        "wrong_count":     wrong_count,
        "ignore_count":    ignore_count,
        "manual_count":    manual_count,
        "retrain_ready":   (right_count + wrong_count) >= 50,
        "retrain_running": not _retrain_lock_flag.is_set(),
        "model":           model_meta,
    }


@app.get("/api/detection/compare")
def get_detection_compare(
    symbol:    str = Query("EURUSD"),
    timeframe: str = Query("1h"),
):
    """
    Compare baseline boxes vs model-generated boxes.
    Returns counts and overlap (agreement) ratio.
    """
    cached = _cache_get(f"detection_compare_{symbol}_{timeframe}")
    if cached is not None:
        return cached

    # Count baseline boxes from /consolidations cache or live
    baseline_count = 0
    cached_zones = _cache_get("consolidations")
    if cached_zones and "zones" in cached_zones:
        baseline_count = sum(
            1 for z in cached_zones["zones"]
            if z.get("timeframe", "").lower() == timeframe.lower()
        )

    # Get model boxes (reuse endpoint logic)
    model_resp = get_model_boxes(symbol=symbol, timeframe=timeframe, candles=500, threshold=0.5)
    model_boxes = model_resp.get("boxes", []) if model_resp.get("status") == "ok" else []
    model_count = len(model_boxes)

    # Overlap: model box time window overlaps with any baseline box
    overlap_count = 0
    if cached_zones and "zones" in cached_zones and model_boxes:
        baseline_zones = [z for z in cached_zones["zones"]
                          if z.get("timeframe", "").lower() == timeframe.lower()]
        for mb in model_boxes:
            for bz in baseline_zones:
                ms, me = mb["timeStart"], mb["timeEnd"]
                bs, be = bz["timeStart"], bz["timeEnd"]
                if ms < be and me > bs:  # temporal overlap
                    ph_overlap = min(mb["priceHigh"], bz["priceHigh"]) > max(mb["priceLow"], bz["priceLow"])
                    if ph_overlap:
                        overlap_count += 1
                        break

    denom = max(baseline_count, model_count, 1)
    agreement_ratio = round(overlap_count / denom, 4)

    result = {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "baseline_count": baseline_count,
        "model_count": model_count,
        "overlap_count": overlap_count,
        "agreement_ratio": agreement_ratio,
        "model_version": _detection_scorer.version if _detection_scorer else "none",
    }
    _cache_set(f"detection_compare_{symbol}_{timeframe}", result)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
