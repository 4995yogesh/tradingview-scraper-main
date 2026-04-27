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

# Load API keys from .env file if present
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

# ── ML imports ────────────────────────────────────────────────────────────────
import hashlib
try:
    from ml.db import init_db as _ml_init_db
    from ml import scorer as _ml_scorer
    from ml import db as _ml_db
    _ML_AVAILABLE = True
except ImportError as _ml_err:
    _ML_AVAILABLE = False
    _ml_init_db = None
    _ml_scorer = None
    _ml_db = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _compute_box_id_long(symbol: str, zone: dict) -> str:
    """sha256(symbol:tf:tStart:tEnd:pH:pL) → first 16 hex chars."""
    key = (
        f"{symbol}:{zone['timeframe']}:"
        f"{zone.get('timeStart', zone.get('time_start_ms'))}:"
        f"{zone.get('timeEnd', zone.get('time_end_ms'))}:"
        f"{float(zone.get('priceHigh', zone.get('price_high') or 0)):.5f}:"
        f"{float(zone.get('priceLow', zone.get('price_low') or 0)):.5f}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]

def _compute_box_id_short(symbol: str, zone: dict) -> str:
    """sha256(symbol:tf:tStart) → first 16 hex chars."""
    key = f"{symbol}:{zone['timeframe']}:{zone.get('timeStart', zone.get('time_start_ms'))}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]

# ── Constants ─────────────────────────────────────────────────────────────────

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w", "1M": "1M",
    "1D": "1d", "1W": "1w",
}

# Timeframes stored in SQLite via routine gap-fill (intra-day are derived from 5m)
PERSISTENT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

# Symbols to pre-load and gap-fill on startup
PERSISTENT_SYMBOLS = [("OANDA", "EURUSD")]

# Seconds per bar for each timeframe (used for gap calculation)
TF_INTERVAL_SECS = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}

# Per-timeframe fetch limits for routine refreshes (not first-time backfills)
TF_FETCH_LIMIT = {
    "1m": 300, "5m": 400, "15m": 500,
    "1h": 600, "4h": 700, "1d": 800, "1w": 600, "1M": 300,
}

# Watchlist symbols
WATCHLIST_SYMBOLS = [
    {"exchange": "OANDA", "symbol": "EURUSD"},
]

# Track which series are currently being gap-filled (to avoid double-fetching)
_gap_filling: set = set()
_gap_filling_lock = threading.Lock()

# ── Bucket alignment helper (CRITICAL for HTF dedup) ─────────────────────────

def _snap_to_bucket(ts: int, timeframe: str) -> int:
    """
    Snap a unix-second timestamp to the lower bucket boundary for its timeframe.
    Example: 4H candle at ts=14402 → snapped to 14400.
    This is the server-side getBucketTime() equivalent.
    """
    bucket_secs = TF_INTERVAL_SECS.get(timeframe)
    if not bucket_secs:
        return ts
    return (ts // bucket_secs) * bucket_secs

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

def clear_consolidations_cache():
    """Wipe the consolidations cache to ensure fresh labels are served immediately."""
    with _cache_lock:
        if "consolidations" in _cache_store:
            del _cache_store["consolidations"]
            logger.info("[cache] Consolidations cache cleared")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_candles_for_ui(raw_candles, timeframe: str):
    """
    Convert raw candle dicts into the exact shape lightweight-charts expects.
    CRITICAL: intraday timestamps are snapped to bucket boundaries to prevent
    duplicate or misaligned HTF candles (e.g. 4H arriving at 14402 instead of 14400).
    Returns (candle_data, volume_data) sorted ascending, strictly deduplicated.
    """
    use_timestamp = timeframe in ["1m", "5m", "15m", "1h", "4h"]
    # Map<time_val, candle> — last-write-wins, enforces single candle per bucket
    candle_map: dict = {}
    volume_map: dict = {}

    for c in raw_candles:
        # Accept 'ts' (DB rows), 'timestamp' (HistoricalFetcher), or 'time' (RAM storage)
        if "ts" in c:
            ts = int(c["ts"])
        elif "timestamp" in c:
            ts = int(c["timestamp"])
        else:
            # 'time' key: could be unix-sec int or 'YYYY-MM-DD' string
            raw_time = c["time"]
            if isinstance(raw_time, str):
                if use_timestamp:
                    # Parse date string to unix seconds
                    try:
                        ts = int(datetime.strptime(raw_time, "%Y-%m-%d").replace(tzinfo=IST).timestamp())
                    except Exception:
                        continue
                else:
                    # daily/weekly: use string as-is
                    candle_map[raw_time] = {
                        "time":  raw_time,
                        "open":  round(float(c["open"]),  5),
                        "high":  round(float(c["high"]),  5),
                        "low":   round(float(c["low"]),   5),
                        "close": round(float(c["close"]), 5),
                    }
                    volume_map[raw_time] = {
                        "time":  raw_time,
                        "value": float(c.get("volume", 0)),
                        "color": "rgba(38,166,154,0.5)" if float(c["close"]) >= float(c["open"]) else "rgba(239,83,80,0.5)",
                    }
                    continue
            else:
                ts = int(raw_time)

        # Detect milliseconds: > year 2100 in seconds
        if ts > 4_102_444_800:
            ts = ts // 1000

        if use_timestamp:
            # CRITICAL: snap to bucket boundary — eliminates near-duplicate HTF candles
            time_val = _snap_to_bucket(ts, timeframe)
        else:
            # OANDA forex 1d candles open at 21:00/22:00 UTC (17:00 EST).
            # +4h shifts into the next calendar day in UTC, giving correct trading-date labels:
            #   Sun 21:00 UTC + 4h → Mon 01:00 UTC → "Monday" (Monday's candle) ✓
            #   Fri 21:00 UTC + 4h → Sat 01:00 UTC → weekday=5 → filtered ✓
            dt_local = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=4)
            if dt_local.weekday() >= 5:   # 5=Sat, 6=Sun — market closed
                continue
            time_val = dt_local.strftime("%Y-%m-%d")

        candle_map[time_val] = {
            "time":  time_val,
            "open":  round(float(c["open"]),  5),
            "high":  round(float(c["high"]),  5),
            "low":   round(float(c["low"]),   5),
            "close": round(float(c["close"]), 5),
        }
        volume_map[time_val] = {
            "time":  time_val,
            "value": float(c.get("volume", 0)),
            "color": "rgba(38,166,154,0.5)" if float(c["close"]) >= float(c["open"]) else "rgba(239,83,80,0.5)",
        }

    candle_data = sorted(candle_map.values(), key=lambda x: x["time"])
    volume_data = sorted(volume_map.values(), key=lambda x: x["time"])
    return candle_data, volume_data


def resample_candles(source_candles: list, target_tf: str) -> list:
    """
    Aggregate lower-TF candles into higher-TF OHLCV buckets.
    Uses strict getBucketTime alignment. One candle per bucket, always.
    """
    tf_minutes = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}.get(target_tf)
    if not tf_minutes or not source_candles:
        return source_candles

    bucket_size_secs = tf_minutes * 60
    buckets: dict = {}   # bucket_ts -> candle dict (Map = one entry per bucket)

    for c in source_candles:
        ts = int(c.get("ts", c.get("timestamp", c.get("time", 0))))
        if not ts:
            continue

        # Detect milliseconds (year > 2100 in seconds = > 4102444800)
        if ts > 4_102_444_800:
            ts = ts // 1000

        # getBucketTime: snap to bucket boundary
        bucket_ts = (ts // bucket_size_secs) * bucket_size_secs

        if bucket_ts not in buckets:
            # First candle in bucket → set open
            buckets[bucket_ts] = {
                "ts":     bucket_ts,
                "open":   float(c["open"]),
                "high":   float(c["high"]),
                "low":    float(c["low"]),
                "close":  float(c["close"]),
                "volume": float(c.get("volume", 0.0)),
            }
        else:
            # Subsequent candles → update high/low/close only
            b = buckets[bucket_ts]
            b["high"]   = max(b["high"],  float(c["high"]))
            b["low"]    = min(b["low"],   float(c["low"]))
            b["close"]  = float(c["close"])   # last close wins
            b["volume"] += float(c.get("volume", 0.0))

    # Sort strictly ascending — guaranteed no duplicates (Map enforces 1 entry/bucket)
    result = [buckets[k] for k in sorted(buckets.keys())]
    return result


def _seed_storage(exchange: str, symbol: str, timeframe: str,
                  raw_candles: list, prepend: bool = False):
    """
    1. Persist raw candles to SQLite (write-through).
    2. Load them into the in-memory DataStorage deque.
    3. Stamp the last_refresh time so the freshness check works.
    """
    current_time = int(time.time())
    tf_secs = TF_INTERVAL_SECS.get(timeframe, 60)
    
    closed_candles = []
    for c in raw_candles:
        ts = int(float(c.get("timestamp", c.get("ts", c.get("time", 0)))))
        if ts > 4_102_444_800:
            ts //= 1000
        bucket_ts = _snap_to_bucket(ts, timeframe)
        if current_time >= bucket_ts + tf_secs:
            # For daily/weekly: reject weekend candles before they enter SQLite.
            # OANDA 17:00 EST open equates to 21:00/22:00 UTC. 
            # We must shift +4h to evaluate the actual trading day (Sun 21:00 + 4h = Monday).
            if timeframe in ("1d", "1w"):
                dow = (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=4)).weekday()
                if dow >= 5:   # 5=Sat, 6=Sun
                    continue
            closed_candles.append(c)

    if not closed_candles:
        return

    # ── 1. Strict Closed-Candles Write to SQLite ──────────────────────────────
    candle_db.upsert_candles(exchange, symbol, timeframe, closed_candles)
    candle_db.log_refresh(exchange, symbol, timeframe, int(time.time()))

    # ── 2. Format and push to RAM ─────────────────────────────────────────────
    use_timestamp = timeframe in ["1m", "5m", "15m", "1h", "4h"]
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

    use_timestamp = timeframe in ["1m", "5m", "15m", "1h", "4h"]
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

        # First-time (empty DB) or DB too shallow — deep backfill
        FIRST_FETCH = {
            "1m": 10000, "5m": 15000, "15m": 15000, 
            "1h": 10000, "4h": 10000, "1d": 5000, "1w": 2000,
        }

        # Minimum bars to (re-)fetch on every startup to heal internal gaps.
        # e.g. 5m × 300 = 25 h — covers any overnight / weekend hole.
        STARTUP_MIN = {
            "1m": 1500, "5m": 800, "15m": 600,
            "1h": 400, "4h": 250, "1d": 200, "1w": 100,
        }

        db_count = candle_db.count(exchange, symbol, timeframe)
        if latest_ts is None or db_count < FIRST_FETCH.get(timeframe, 5000):
            fetch_limit = FIRST_FETCH.get(timeframe, 5000)
            logger.info("[gap-fill] Deep backfill for %s:%s [%s] limit=%d",
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
            start_date = latest_ts if latest_ts else None,
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
    Parallel gap-fill across all symbol/timeframe pairs.
    Shortest timeframes first within each batch to minimise wall-clock time.
    Uses a thread-pool so all TFs run concurrently instead of sequentially.
    """
    ordered = sorted(
        PERSISTENT_TIMEFRAMES,
        key=lambda tf: TF_INTERVAL_SECS.get(tf, 0),
        reverse=False,  # 1m first, 1w last (for logging clarity)
    )
    tasks = [
        (exchange, symbol, tf)
        for exchange, symbol in PERSISTENT_SYMBOLS
        for tf in ordered
    ]
    max_workers = min(_CPU_WORKERS, len(tasks) or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_gap_fill, ex, sym, tf): (ex, sym, tf)
                   for ex, sym, tf in tasks}
        for fut in as_completed(futures):
            ex, sym, tf = futures[fut]
            try:
                fut.result()
            except Exception as exc:
                logger.error("[gap-fill] %s:%s [%s] pool error: %s", ex, sym, tf, exc)


# ── Delta-Engine: 1m-only external fetch + HTF in-process synthesis ──────────

# Which timeframes are synthesized from 1m candles (intraday)
_INTRADAY_TFS  = ["5m", "15m", "1h", "4h"]
# Which timeframes are synthesized from 5m candles
_INTERDAY_TFS  = ["1d", "1w"]
# OANDA day boundary: 22:00 UTC (17:00 EST)
_DAY_OPEN_UTC_HOUR = 22


def _get_day_start_ts() -> int:
    """Return the unix-second of the most recent OANDA trading day open (22:00 UTC)."""
    now_utc = datetime.now(timezone.utc)
    candidate = now_utc.replace(hour=_DAY_OPEN_UTC_HOUR, minute=0, second=0, microsecond=0)
    if now_utc < candidate:
        candidate -= timedelta(days=1)
    return int(candidate.timestamp())


def _build_htf_from_1m(exchange: str, symbol: str, target_tf: str) -> list:
    """
    Pull 1m closed candles from SQLite for the last 48h.
    Aggregate them into target_tf buckets.
    48h window ensures overnight gaps (up to 25h) are covered.
    """
    since_ts = int(time.time()) - 48 * 3600   # 48h lookback
    raw_1m = candle_db.get_candles_since(exchange, symbol, "1m", since_ts)
    if not raw_1m:
        return []

    bucket_secs = TF_INTERVAL_SECS.get(target_tf, 300)
    buckets: dict = {}
    for c in raw_1m:
        ts = int(c.get("ts", c.get("timestamp", 0)))
        if ts < since_ts:
            continue   # skip candles outside 48h window
        bucket_ts = (ts // bucket_secs) * bucket_secs
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {
                "ts":    bucket_ts, "open": float(c["open"]),
                "high":  float(c["high"]), "low":  float(c["low"]),
                "close": float(c["close"]), "volume": float(c.get("volume", 0)),
            }
        else:
            b = buckets[bucket_ts]
            b["high"]   = max(b["high"],  float(c["high"]))
            b["low"]    = min(b["low"],   float(c["low"]))
            b["close"]  = float(c["close"])
            b["volume"] += float(c.get("volume", 0))

    return [buckets[k] for k in sorted(buckets)]


def _build_htf_from_5m(exchange: str, symbol: str, target_tf: str) -> list:
    """
    Pull all 5m closed candles from SQLite for the last 10 days.
    Aggregate them into target_tf buckets (1d / 1w).
    """
    since_ts = int(time.time()) - 10 * 86400
    raw_5m = candle_db.get_candles_since(exchange, symbol, "5m", since_ts)
    if not raw_5m:
        return []

    bucket_secs = TF_INTERVAL_SECS.get(target_tf, 86400)
    buckets: dict = {}
    for c in raw_5m:
        ts = int(c.get("ts", c.get("timestamp", 0)))
        bucket_ts = (ts // bucket_secs) * bucket_secs
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {
                "ts":    bucket_ts, "open": float(c["open"]),
                "high":  float(c["high"]), "low":  float(c["low"]),
                "close": float(c["close"]), "volume": float(c.get("volume", 0)),
            }
        else:
            b = buckets[bucket_ts]
            b["high"]   = max(b["high"],  float(c["high"]))
            b["low"]    = min(b["low"],   float(c["low"]))
            b["close"]  = float(c["close"])
            b["volume"] += float(c.get("volume", 0))

    return [buckets[k] for k in sorted(buckets)]


def _synthesize_htf_candles(exchange: str, symbol: str):
    """
    Re-compute all intraday HTF live buckets from 1m data,
    and interday buckets from 5m data.
    Merges synthesized candles into RAM storage.
    """
    # ── intraday TFs from 1m ──────────────────────────────────────────────
    for tf in _INTRADAY_TFS:
        try:
            synth = _build_htf_from_1m(exchange, symbol, tf)
            if synth:
                _seed_storage(exchange, symbol, tf, synth)
                logger.debug("[synth] %s:%s [%s] → %d buckets", exchange, symbol, tf, len(synth))
        except Exception as exc:
            logger.error("[synth] %s:%s [%s] failed: %s", exchange, symbol, tf, exc)

    # ── interday TFs from 5m ─────────────────────────────────────────────
    for tf in _INTERDAY_TFS:
        try:
            synth = _build_htf_from_5m(exchange, symbol, tf)
            if synth:
                _seed_storage(exchange, symbol, tf, synth)
                logger.debug("[synth] %s:%s [%s] → %d buckets", exchange, symbol, tf, len(synth))
        except Exception as exc:
            logger.error("[synth] %s:%s [%s] failed: %s", exchange, symbol, tf, exc)


def _fetch_latest_candles(exchange: str, symbol: str, timeframe: str, limit: int = 20):
    """
    Fetch the very latest 1m candles from TradingView via HistoricalFetcher
    and merge into SQLite + RAM cache.
    Dynamic limit covers any gap since the last stored candle.
    """
    key = (exchange, symbol, timeframe)
    with _gap_filling_lock:
        if key in _gap_filling:
            return   # gap-fill already running; skip
        _gap_filling.add(key)
    try:
        interval  = TF_INTERVAL_SECS.get(timeframe, 60)
        latest_ts = candle_db.get_latest_ts(exchange, symbol, timeframe)
        if latest_ts is not None:
            gap_secs      = max(0, int(time.time()) - latest_ts)
            missing_bars  = gap_secs // interval + 5
            dynamic_limit = max(limit, int(missing_bars))
        else:
            dynamic_limit = limit
        dynamic_limit = min(dynamic_limit, 1500)

        if dynamic_limit > limit:
            logger.info("[1m-fetch] %s:%s gap=%ds → fetching %d bars",
                        exchange, symbol,
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
            logger.info("[1m-fetch] ✓ %s:%s refreshed %d 1m candles", exchange, symbol, len(raw))
        else:
            logger.warning("[1m-fetch] %s:%s — TV returned no 1m candles", exchange, symbol)
    except Exception as exc:
        logger.error("[1m-fetch] %s:%s failed: %s", exchange, symbol, exc)
    finally:
        with _gap_filling_lock:
            _gap_filling.discard(key)


_stop_refresh = threading.Event()

def _periodic_refresh_loop():
    """
    Delta-Engine background thread:
    1. Every 5 seconds: fetch only 1m candles from TradingView.
    2. After each 1m fetch: synthesize all HTF candles from DB.
       - 5m/15m/1h/4h → from today's 1m candles (intraday only).
       - 1d/1w        → from 5m candles (last 10 days).
    No external TradingView calls are made for any HTF.
    """
    time.sleep(30)  # let gap-fill settle first
    while not _stop_refresh.is_set():
        now = time.time()
        next_period = (int(now) // 5 + 1) * 5
        sleep_secs  = max(0, next_period - time.time())
        if _stop_refresh.wait(timeout=sleep_secs):
            break

        for exchange, symbol in PERSISTENT_SYMBOLS:
            # Step 1: fetch only 1m from TradingView
            _fetch_latest_candles(exchange, symbol, "1m", limit=10)
            # Step 2: synthesize all HTFs from DB (background, always)
            _synthesize_htf_candles(exchange, symbol)
            logger.info("[delta] ✓ %s:%s cycle complete", exchange, symbol)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Start event-driven streaming pipeline
    pipeline.start()

    # 2. Load persisted candles into RAM in parallel (pure SQL reads — WAL safe)
    logger.info("=== Loading persisted candle data from SQLite ===")
    load_tasks = [
        (exchange, symbol, tf)
        for exchange, symbol in PERSISTENT_SYMBOLS
        for tf in PERSISTENT_TIMEFRAMES
    ]
    with ThreadPoolExecutor(max_workers=min(_CPU_WORKERS, len(load_tasks) or 1)) as pool:
        futs = {pool.submit(_load_db_into_ram, ex, sym, tf): (ex, sym, tf)
                for ex, sym, tf in load_tasks}
        for fut in as_completed(futs):
            ex, sym, tf = futs[fut]
            try:
                fut.result()
            except Exception as exc:
                logger.error("DB load failed %s:%s [%s]: %s", ex, sym, tf, exc)

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

    # 5. Init ML DB and load promoted model
    if _ML_AVAILABLE:
        try:
            _ml_init_db()
            _ml_scorer.load_model()
            
            # Restore persistent FP/FN boxes from DB
            from ml import trainer as _trainer
            _trainer.reload_error_boxes()
            
            logger.info("=== ML system initialized ===")
        except Exception as _ml_exc:
            logger.error("ML init failed (non-fatal): %s", _ml_exc)

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

# ── Mount ML router ────────────────────────────────────────────────────────────
if _ML_AVAILABLE:
    try:
        from ml_router import router as _ml_router
        app.include_router(_ml_router)
        logger.info("ML router mounted at /api/ml/*")
    except Exception as _mr_exc:
        logger.error("Failed to mount ML router: %s", _mr_exc)


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


def parse_end_time(end_time):
    if end_time is None:
        return None
    try:
        return int(end_time)
    except Exception:
        pass
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(end_time, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


@app.get("/api/ohlc")
def get_ohlc(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Unsupported timeframe '{timeframe}'. Choose from: {list(TIMEFRAME_MAP)}")

    if ":" in symbol:
        exchange, symbol = symbol.split(":", 1)

    parsed_end = parse_end_time(end_time)
    logger.info("OHLC (DB-First) → %s:%s tf=%s candles=%d end=%s", exchange, symbol, timeframe, candles, end_time)
    
    is_recent = end_time is None

    # 1. Fetch CLOSED candles strictly from SQLite Database
    closed_candles = candle_db.get_candles(exchange, symbol, timeframe, count=candles, end_ts=parsed_end)
    
    # 2. Bridge Live HTF Segment using 1m DB & RAM partials
    if is_recent and timeframe != "1m" and closed_candles:
        latest_closed_ts = int(float(closed_candles[-1].get("ts", closed_candles[-1].get("time", 0))))
        tf_secs = TF_INTERVAL_SECS.get(timeframe, 60)
        unclosed_boundary = latest_closed_ts + tf_secs
        
        # Pull any closed 1m segments bridging the gap out of DB securely
        live_1m = candle_db.get_candles(exchange, symbol, "1m", count=4000, start_ts=unclosed_boundary)
        
        # Extract purely unclosed live 1m tick from RAM cache
        latest_1m_ram = storage.get_candles(exchange, symbol, "1m", count=5)
        ram_ticks = []
        for c in latest_1m_ram:
            ts = int(float(c.get("timestamp", c.get("ts", c.get("time", 0)))))
            if ts >= unclosed_boundary:
                ram_ticks.append(c)
                
        # Consolidate arrays
        unclosed_ticks = live_1m + ram_ticks
        if unclosed_ticks:
            bridge = resample_candles(unclosed_ticks, timeframe)
            if bridge:
                closed_candles.append(bridge[0])

    elif timeframe == "1m" and is_recent and closed_candles:
        # 1m just appends its active floating tick cleanly
        ram_ticks = storage.get_candles(exchange, symbol, "1m", count=1)
        if ram_ticks:
            closed_candles.append(ram_ticks[-1])

    cd, vd = _format_candles_for_ui(closed_candles, timeframe)
    return {"status": "success", "candleData": cd, "volumeData": vd}

@app.get("/api/consolidation")
def get_consolidation(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    """Return consolidation boxes for given series."""
    use_timestamp = timeframe in ["1m", "5m", "15m", "1h", "4h"]
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
            stored = storage.get_candles(exchange, symbol, tf, count=10000)
            if not stored or len(stored) < 5:
                return zones

            use_timestamp = tf in ["1m", "5m", "15m", "1h", "4h"]
            df = pd.DataFrame(stored)

            if use_timestamp:
                df.index = pd.to_datetime(df["time"], unit='s', utc=True)
            else:
                # Force utc=True for Daily/Weekly strings to ensure deterministic UTC timestamps
                df.index = pd.to_datetime(df["time"], utc=True)

            apply_time_filter = tf in ["1m", "5m", "15m", "1h"]
            boxes_df = consolidation_boxes(df, min_bars=5, use_time_filter=apply_time_filter)
            if boxes_df.empty:
                return zones

            df_len = len(df)
            idx    = df.index
            for _, row in boxes_df.iterrows():
                try:
                    si = int(row["start"])
                    ei = int(row["end"])
                    if si >= df_len or ei >= df_len:
                        continue
                    ts_start = int(pd.Timestamp(idx[si]).timestamp() * 1000)
                    ts_end   = int(pd.Timestamp(idx[ei]).timestamp() * 1000)
                    zones.append({
                        "timeframe": tf,
                        "timeStart": ts_start,
                        "timeEnd":   ts_end,
                        "priceHigh": float(row["top"]),
                        "priceLow":  float(row["bottom"]),
                    })
                except Exception as inner_exc:
                    logger.debug("Zone parse error %s [%s]: %s", symbol, tf, inner_exc)
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

    # ── Enrich zones with ML box_id, label, score ────────────────────────────
    if _ML_AVAILABLE:
        try:
            # 1. Inject persistent Error Boxes (FP/FN) so they are always visible for feedback
            from ml.trainer import TRAINING_STATE
            error_boxes = []
            for typ in ["fp", "fn"]:
                for eb in TRAINING_STATE["error_boxes"].get(typ, []):
                    # Eb has: box_id, timeframe, timeStart, timeEnd, priceHigh, priceLow, ...
                    # Ensure it has basic viz fields
                    error_boxes.append({
                        "timeframe": eb.get("timeframe"),
                        "timeStart": eb.get("timeStart") or eb.get("time_start_ms"),
                        "timeEnd":   eb.get("timeEnd")   or eb.get("time_end_ms"),
                        "priceHigh": float(eb.get("priceHigh") or eb.get("price_high") or 0),
                        "priceLow":  float(eb.get("priceLow")  or eb.get("price_low")  or 0),
                        "box_id":    eb.get("box_id"),
                        "symbol":    eb.get("symbol") or "EURUSD",
                        "is_error":  True,
                        "error_type": typ
                    })
            
            # Combine — if box_id already exists in all_zones, don't duplicate
            existing_ids = {z["box_id"] for z in all_zones if "box_id" in z}
            for eb in error_boxes:
                if eb["box_id"] not in existing_ids:
                    all_zones.append(eb)

            # 2. Assign primary box_id and identify potential legacy matches
            for z in all_zones:
                sym = z.get("symbol", "EURUSD")
                z["box_id_long"] = _compute_box_id_long(sym, z)
                z["box_id_short"] = _compute_box_id_short(sym, z)
                if "box_id" not in z:
                    z["box_id"] = z["box_id_long"] # Default to long

            # Collect ALL possible IDs to check in DB
            all_possible_ids = []
            for z in all_zones:
                all_possible_ids.extend([z["box_id_long"], z["box_id_short"]])
            
            scores_map = _ml_scorer.batch_score(all_possible_ids)
            labels_map = _ml_db.get_labels_for_boxes(all_possible_ids)

            for z in all_zones:
                # Prioritize Long ID for richness, but switch to Short if label exists there
                # Also check scores for both
                bL = z["box_id_long"]
                bS = z["box_id_short"]
                
                # Winner selection: prioritize human label
                winner_id = bL # default
                lbl_obj = labels_map.get(bL)
                if not lbl_obj:
                    # Fallback to legacy short ID
                    lbl_obj = labels_map.get(bS)
                    if lbl_obj:
                        winner_id = bS
                
                # If we found a label (new or legacy), use THAT ID for the chart link
                z["box_id"] = winner_id
                z["score"] = scores_map.get(winner_id, _ml_scorer.FALLBACK)
                
                if lbl_obj:
                    z["label"] = lbl_obj["label"]
                    z["comment"] = lbl_obj["comment"]
                    z["lesson"] = lbl_obj["lesson"]
        except Exception as _enrich_exc:
            logger.warning("ML enrichment failed (non-fatal): %s", _enrich_exc)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)