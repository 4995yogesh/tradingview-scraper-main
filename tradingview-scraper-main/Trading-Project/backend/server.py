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



from fastapi import FastAPI, HTTPException, Query, Body
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
from indicators.user_style_learner import UserStyleLearner
from indicators.adaptive_consolidation import adaptive_consolidation_boxes
import dukascopy_seeder  # ← Dukascopy historical seeder

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

# Symbols to pre-load and gap-fill on startup — configured symbols (EURUSD and XAUUSD)
PERSISTENT_SYMBOLS = [
    ("OANDA", "EURUSD"),
    ("OANDA", "XAUUSD"),
]

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
    {"exchange": "OANDA", "symbol": "XAUUSD"},
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

    # ── 1. Strict Closed-Candles Write to SQLite ──────────────────────────────
    if closed_candles:
        candle_db.upsert_candles(exchange, symbol, timeframe, closed_candles)
        candle_db.log_refresh(exchange, symbol, timeframe, int(time.time()))
    
    if not raw_candles:
        return

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
    # Only load the latest 10,000 candles into RAM cache to save memory and ensure instant server startup
    db_rows = candle_db.get_candles(exchange, symbol, timeframe, count=10000)
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
        is_deep_backfill = (latest_ts is None or db_count < FIRST_FETCH.get(timeframe, 5000))
        
        if is_deep_backfill:
            fetch_limit = FIRST_FETCH.get(timeframe, 5000)
            logger.info("[gap-fill] Deep backfill for %s:%s [%s] limit=%d",
                        exchange, symbol, timeframe, fetch_limit)
            start_date = None
        else:
            gap_secs     = now_ts - latest_ts
            missing_bars = max(gap_secs // interval + 20, STARTUP_MIN.get(timeframe, 200))
            fetch_limit  = int(missing_bars)
            logger.info("[gap-fill] %s:%s [%s] gap=%ds → fetching %d bars (includes startup min)",
                        exchange, symbol, timeframe, gap_secs, fetch_limit)
            start_date = latest_ts

        cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
        jwt_value    = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
        fetcher      = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)

        raw_candles = fetcher.fetch_historical_data(
            exchange   = exchange,
            symbol     = symbol,
            timeframe  = timeframe,
            limit      = fetch_limit,
            start_date = start_date,
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


def _live_stream_worker(exchange: str, symbol: str):
    """Background worker that streams live 1m ticks from TradingView WebSockets."""
    from tradingview_scraper.symbols.stream.price import RealTimeData
    while not _stop_refresh.is_set():
        try:
            logger.info("[ws-stream] Starting WebSocket stream for %s:%s", exchange, symbol)
            rtd = RealTimeData()
            generator = rtd.get_ohlcv(f"{exchange}:{symbol}")
            
            for packet in generator:
                if _stop_refresh.is_set():
                    break
                    
                m = packet.get("m")
                if m in ("timescale_update", "du"):
                    series = packet.get("p", [{}, {}])[1].get("sds_1", {}).get("s", [])
                    if not series:
                        continue
                        
                    raw_candles = []
                    for entry in series:
                        v = entry.get("v", [])
                        if len(v) >= 5:
                            candle = {
                                "timestamp": v[0],
                                "open": v[1],
                                "high": v[2],
                                "low": v[3],
                                "close": v[4]
                            }
                            if len(v) > 5:
                                candle["volume"] = v[5]
                            raw_candles.append(candle)
                            
                    if raw_candles:
                        _seed_storage(exchange, symbol, "1m", raw_candles)
                        
        except Exception as exc:
            logger.error("[ws-stream] Stream error for %s:%s : %s", exchange, symbol, exc)
            time.sleep(5) # backoff before reconnecting


_stop_refresh = threading.Event()

def _periodic_refresh_loop():
    """
    Delta-Engine background thread:
    1. Every 5 seconds: synthesize all HTF candles from DB.
       - 5m/15m/1h/4h → from today's 1m candles (intraday only).
       - 1d/1w        → from 5m candles (last 10 days).
    No external TradingView calls are made for any HTF.
    """
    last_synth_ts = {}
    time.sleep(30)  # let gap-fill settle first
    while not _stop_refresh.is_set():
        now = time.time()
        next_period = (int(now) // 5 + 1) * 5
        sleep_secs  = max(0, next_period - time.time())
        if _stop_refresh.wait(timeout=sleep_secs):
            break

        for exchange, symbol in PERSISTENT_SYMBOLS:
            latest_1m = candle_db.get_latest_ts(exchange, symbol, "1m")
            if latest_1m and latest_1m == last_synth_ts.get((exchange, symbol)):
                continue # No new closed 1m candle; skip expensive HTF synthesis
            
            last_synth_ts[(exchange, symbol)] = latest_1m
            
            # Step 2: synthesize all HTFs from DB (background, always)
            # Run asynchronously to avoid blocking the 5s refresh loop
            threading.Thread(target=_synthesize_htf_candles, args=(exchange, symbol), daemon=True).start()

def _auto_label_loop():
    """
    Background loop to auto-label boxes that haven't been processed yet.
    """
    time.sleep(45) # let system warm up
    while not _stop_refresh.is_set():
        try:
            from ml.quality.autolabel.auto_labeller import auto_label_pipeline
            from ml.quality.db import get_auto_labels
            from ml.quality.features import QualityExtractor
            from ml.llm_translator import _get_client as get_gemini_client
            
            # 1. Get all current boxes
            all_resp = get_consolidations_all()
            all_zones = all_resp.get("zones", [])
            if not all_zones:
                time.sleep(30)
                continue
                
            # 2. Filter unlabeled
            existing_auto = get_auto_labels()
            unlabeled = [z for z in all_zones if z.get("box_id") and z["box_id"] not in existing_auto]
            
            if unlabeled:
                logger.info("[auto-label] Processing %d new boxes", len(unlabeled))
                # Only process newest 10 at a time to avoid blocking
                unlabeled.sort(key=lambda x: x.get("timeEnd", 0), reverse=True)
                batch = unlabeled[:10]
                
                extractor = QualityExtractor(storage.get_candles)
                gemini = get_gemini_client() # Fallback to Mock is handled in gemini_label
                
                auto_label_pipeline(batch, extractor, gemini)
                logger.info("[auto-label] Batch complete")
                
        except Exception as e:
            logger.error("[auto-label] Loop error: %s", e)
            
        if _stop_refresh.wait(timeout=60):
            break


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

    # Auto-clean cache (__pycache__)
    try:
        import glob
        import shutil
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        pycache_dirs = glob.glob(os.path.join(backend_dir, "**/__pycache__"), recursive=True)
        for d in pycache_dirs:
            shutil.rmtree(d, ignore_errors=True)
        logger.info(f"Cleared {len(pycache_dirs)} __pycache__ directories.")
    except Exception as e:
        logger.warning(f"Failed to clear __pycache__: {e}")

    # Print diagnostics
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import config
    config.print_diagnostics()

    # 3. Start Dukascopy seeder (background — fills historical gaps before TV gap-fill)
    seed_thread = threading.Thread(
        target=dukascopy_seeder.seed_missing_pairs,
        args=(candle_db,),
        kwargs={"exchange": "OANDA"},
        name="dukascopy-seeder",
        daemon=True,
    )
    seed_thread.start()
    logger.info("=== Dukascopy seeder thread started ===")

    # 4. Start background gap-fill (non-blocking — server ready immediately)
    gap_thread = threading.Thread(
        target=_run_all_gap_fills,
        name="gap-filler",
        daemon=True,
    )
    gap_thread.start()
    logger.info("=== Gap-fill thread started — server accepting requests ===")

    # 4. Start periodic HTF synthesis loop
    _stop_refresh.clear()
    refresh_thread = threading.Thread(
        target=_periodic_refresh_loop,
        name="periodic-refresh",
        daemon=True,
    )
    refresh_thread.start()
    logger.info("=== Periodic HTF refresh thread started ===")

    # 4.5 Start WebSocket streaming for live ticks
    for exchange, symbol in PERSISTENT_SYMBOLS:
        ws_thread = threading.Thread(
            target=_live_stream_worker,
            args=(exchange, symbol),
            name=f"live-stream-{symbol}",
            daemon=True,
        )
        ws_thread.start()
    logger.info("=== WebSocket live streams started ===")

    # 5. Init ML DB and load promoted model
    if _ML_AVAILABLE:
        try:
            _ml_init_db()
            _ml_scorer.load_model()
            
            logger.info("=== ML system initialized ===")
            
            # 6. Start Auto-Label Loop
            al_thread = threading.Thread(target=_auto_label_loop, name="auto-labeller", daemon=True)
            al_thread.start()
            logger.info("=== Auto-Label loop started ===")
        except Exception as _ml_exc:
            logger.error("ML init failed (non-fatal): %s", _ml_exc)

    yield  # Server is live

    _stop_refresh.set()
    pipeline.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="TradingView Scraper API", lifespan=lifespan)

from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)

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
        from ml.quality.quality_router import router as _quality_router
        app.include_router(_quality_router)
        logger.info("ML routers mounted at /api/ml/* and /api/ml/quality/*")
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


import time
_OHLC_CACHE = {}

def _cache_get(key: str, ttl_s: float = 8.0):
    if key in _OHLC_CACHE:
        entry = _OHLC_CACHE[key]
        if time.time() - entry['time'] < ttl_s:
            return entry['data']
    return None

def _cache_set(key: str, data: dict):
    _OHLC_CACHE[key] = {
        'time': time.time(),
        'data': data
    }



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
    is_recent = end_time is None

    # ── Short-lived response cache to absorb burst requests ─────────────
    # Hover prefetch + multi-pane identical requests all hit the same cache entry.
    # Use 2.0s for recent/live data so the 5s frontend poll gets fresh data.
    # Use 8.0s for historical requests.
    cache_key = f"ohlc:{exchange}:{symbol}:{timeframe}:{candles}:{end_time}"
    cached_ttl = 2.0 if is_recent else 8.0
    cached = _cache_get(cache_key, ttl_s=cached_ttl)
    if cached is not None:
        logger.debug("OHLC cache hit → %s:%s tf=%s", exchange, symbol, timeframe)
        return cached

    logger.debug("OHLC (RAM-First) → %s:%s tf=%s candles=%d end=%s", exchange, symbol, timeframe, candles, end_time)
    
    # 1. Fetch CLOSED candles strictly from RAM cache (O(1) list slice)
    closed_candles_iter = storage.get_candles(exchange, symbol, timeframe, count=candles, end_time=parsed_end)
    closed_candles = list(closed_candles_iter)
    
    # 2. Bridge Live HTF Segment instantly using 1m RAM partials
    if is_recent and timeframe != "1m" and closed_candles:
        latest_closed_ts = int(float(closed_candles[-1].get("ts", closed_candles[-1].get("time", 0))))
        tf_secs = TF_INTERVAL_SECS.get(timeframe, 60)
        unclosed_boundary = latest_closed_ts + tf_secs
        
        # Pull all recent 1m candles strictly from RAM (instant)
        recent_1m = storage.get_candles(exchange, symbol, "1m", count=1500)
        unclosed_ticks = []
        for c in recent_1m:
            ts = int(float(c.get("timestamp", c.get("ts", c.get("time", 0)))))
            if ts >= unclosed_boundary:
                unclosed_ticks.append(c)
                
        # Consolidate arrays
        if unclosed_ticks:
            bridge = resample_candles(unclosed_ticks, timeframe)
            if bridge:
                closed_candles.append(bridge[0])

    total_in_storage = 0
    with storage.lock:
        try:
            total_in_storage = len(storage.candles[exchange][symbol][timeframe])
        except KeyError:
            pass

    if not closed_candles or (total_in_storage < 50 and timeframe != "1m"):
        # DB is empty or still seeding in background via OANDA/TV scraper.
        # Returning 'loading' tells the frontend to show a status overlay and retry.
        return {"status": "loading"}

    cd, vd = _format_candles_for_ui(closed_candles, timeframe)
    result = {"status": "success", "candleData": cd, "volumeData": vd}
    _cache_set(cache_key, result)
    return result


@app.post("/api/fetch-symbol")
def fetch_symbol_on_demand(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
):
    """
    Trigger an on-demand Dukascopy seed + TradingView gap-fill for a symbol.
    Designed for the frontend sidebar — called when a user switches to a pair
    that may not yet have data in the local DB.
    Returns immediately; seeding runs in a background thread.
    """
    symbol = symbol.upper().strip()
    exchange = exchange.upper().strip()

    def _seed_and_gapfill():
        # Step 1: Dukascopy seed (fast path for deep history)
        dukascopy_seeder.seed_single_symbol(candle_db, symbol, exchange)
        # Step 2: load freshly seeded rows into RAM cache
        for tf in PERSISTENT_TIMEFRAMES:
            _load_db_into_ram(exchange, symbol, tf)
        # Step 3: TradingView gap-fill for recent live data
        for tf in PERSISTENT_TIMEFRAMES:
            _gap_fill(exchange, symbol, tf)
        logger.info("[fetch-symbol] ✓ %s:%s ready", exchange, symbol)

    t = threading.Thread(target=_seed_and_gapfill,
                         name=f"on-demand-{symbol}", daemon=True)
    t.start()
    return {"status": "ok", "message": f"Seeding {exchange}:{symbol} in background"}


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

@app.get("/api/adaptive_consolidation")
def get_adaptive_consolidation(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    """Return adaptive consolidation boxes for given series."""
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
    boxes_df = adaptive_consolidation_boxes(df)
    return {"status": "success", "boxes": boxes_df.to_dict(orient="records"), "candles": stored}

@app.post("/api/adaptive_consolidation/context")
def get_adaptive_consolidation_context(candles: list = Body(...)):
    """Return adaptive consolidation boxes for given candles."""
    if not candles:
        raise HTTPException(400, "No candles provided")
    df = pd.DataFrame(candles)
    if "time" in df.columns:
        try:
            if isinstance(df["time"].iloc[0], (int, float, np.integer)):
                df.set_index(pd.to_datetime(df["time"], unit='s'), inplace=True)
            else:
                df.set_index(pd.to_datetime(df["time"]), inplace=True)
        except Exception as e:
            print("Error setting index in adaptive context:", e)
    
    boxes_df = adaptive_consolidation_boxes(df)
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
            boxes_df = consolidation_boxes(df, min_bars=6, use_time_filter=apply_time_filter)
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
                    zone_data = {
                        "symbol":    symbol,
                        "timeframe": tf,
                        "timeStart": ts_start,
                        "timeEnd":   ts_end,
                        "priceHigh": float(row["top"]),
                        "priceLow":  float(row["bottom"]),
                        "type":      row.get("type", "LOOSE"),
                        "score":     float(row.get("score", 0.0))
                    }
                    # Compute ID and sample for Refinement Training
                    zid = _compute_box_id_long(symbol, zone_data)
                    zone_data["box_id"] = zid
                    zones.append(zone_data)

                    # ── Midnight Filter (IST: 00:00 - 05:59) ─────────────────
                    from datetime import datetime, timezone, timedelta
                    ist = timezone(timedelta(hours=5, minutes=30))
                    dt_ist = datetime.fromtimestamp(ts_start / 1000, tz=timezone.utc).astimezone(ist)
                    
                    is_midnight = 0 <= dt_ist.hour < 6
                    if is_midnight:
                        continue 

                    # Auto-Sampler (5m, 15m, 1h only)
                    # Guard: only sample when ≥15 candles exist after box end (right-side context requirement)
                    if tf in ["5m", "15m", "1h"] and (ei + 15) <= (df_len - 1):
                        try:
                            ctx_s = max(0, si - 25)
                            ctx_e = min(df_len - 1, ei + 25)
                            # Ensure time is converted to string for JSON persistence
                            ctx_df = df.iloc[ctx_s:ctx_e+1].copy()
                            ctx_df['time'] = ctx_df.index.strftime('%Y-%m-%dT%H:%M:%SZ')
                            from training_db import training_db
                            # Initially PENDING_SCREENSHOT until frontend fulfills it
                            training_db.upsert_box(zone_data, ctx_df.to_dict('records'))
                        except Exception as e:
                            logger.debug("Sampling error: %s", e)

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
            
            # Fetch Hybrid Auto-Labels
            from ml.quality.db import get_auto_labels as get_hybrid_labels
            hybrid_map = get_hybrid_labels()

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
                
                # Hybrid Auto-Label Injection
                hybrid_obj = hybrid_map.get(winner_id) or hybrid_map.get(bS) or hybrid_map.get(bL)
                if hybrid_obj:
                    z["auto_label"] = hybrid_obj["label"]
                    z["auto_confidence"] = hybrid_obj["confidence"]
                    z["auto_status"] = hybrid_obj["status"]
                    z["auto_interpretation"] = hybrid_obj.get("reason")

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



# ── REFINEMENT TRAINING ENDPOINTS ───────────────────────────────────────────
@app.get("/api/training/all_boxes")
async def get_all_boxes(limit: int = 200, status: str = None):
    """Returns ALL boxes regardless of status, with full ohlc_context for canvas rendering."""
    import sqlite3
    try:
        with sqlite3.connect("training_set.db", timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                cursor = conn.execute(
                    "SELECT box_id, symbol, timeframe, time_start, time_end, price_high, price_low, ohlc_context, original_meta, user_box, status, created_at FROM review_queue WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT box_id, symbol, timeframe, time_start, time_end, price_high, price_low, ohlc_context, original_meta, user_box, status, created_at FROM review_queue ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            rows = [dict(r) for r in cursor.fetchall()]
            
            import json
            valid_rows = []
            for r in rows:
                try:
                    ctx_str = r["ohlc_context"]
                    if not ctx_str or ctx_str == '[]':
                        # Delete empty boxes immediately to purge them from the list
                        conn.execute("DELETE FROM review_queue WHERE box_id=?", (r["box_id"],))
                        continue
                    
                    ctx = json.loads(ctx_str)
                    if not ctx or len(ctx) == 0:
                        conn.execute("DELETE FROM review_queue WHERE box_id=?", (r["box_id"],))
                        continue
                    doj_count = sum(1 for d in ctx if d['open'] == d['high'] == d['low'] == d['close'])
                    
                    # Detect extreme vertical price gaps (e.g. > 20 pips in EURUSD)
                    # This handles scenarios where data simply jumped across a huge missing time span
                    max_gap = max([0] + [abs(ctx[i]['open'] - ctx[i-1]['close']) for i in range(1, len(ctx))])
                    
                    if doj_count > 3 or max_gap > 0.00200:
                        continue # Skip corrupted/abnormal box
                        
                    valid_rows.append(r)
                except Exception:
                    valid_rows.append(r) # fallback if parse fails
                    
            return {"status": "ok", "boxes": valid_rows, "total": len(valid_rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/training/hard_samples")
async def get_hard_samples():
    import json
    import os
    import sqlite3
    try:
        hard_samples_path = os.path.join("data", "models", "hard_samples.json")
        if not os.path.exists(hard_samples_path):
            return {"status": "ok", "samples": []}
            
        with open(hard_samples_path, "r") as f:
            hard_samples = json.load(f)
            
        # Fetch screenshots and details for these Box IDs
        box_ids = [s["box_id"] for s in hard_samples]
        if not box_ids:
            return {"status": "ok", "samples": []}
            
        with sqlite3.connect("training_set.db", timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join(["?"] * len(box_ids))
            cursor = conn.execute(
                f"SELECT box_id, symbol, timeframe, time_start, time_end, price_high, price_low, ohlc_context, original_meta, user_box, status, created_at, screenshot_b64 FROM review_queue WHERE box_id IN ({placeholders}) AND status NOT IN ('ANALYZED', 'LABELED')",
                box_ids
            )
            rows = [dict(r) for r in cursor.fetchall()]
            
        # Map loss back to rows
        loss_map = {s["box_id"]: s["loss"] for s in hard_samples}
        for r in rows:
            r["loss"] = loss_map.get(r["box_id"], 0.0)
            
        # Sort by loss descending again
        rows.sort(key=lambda x: x["loss"], reverse=True)
            
        return {"status": "ok", "samples": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/training/loss_graphs")
async def get_loss_graphs():
    import os
    import glob
    try:
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(backend_dir, "data", "models")
        if not os.path.exists(models_dir):
            return {"status": "ok", "graphs": []}
            
        pattern = os.path.join(models_dir, "training_val_loss*.png")
        files = glob.glob(pattern)
        
        # Deduplicate: Skip "training_val_loss.png" if there are timestamped files
        # because it's just a duplicate of the latest timestamped one.
        has_timestamped = any(len(os.path.basename(f).split("_")) >= 5 for f in files)
        
        graphs = []
        for f in files:
            basename = os.path.basename(f)
            if basename == "training_val_loss.png" and has_timestamped:
                continue
                
            parts = basename.split("_")
            if len(parts) >= 5:
                date_str = parts[3]
                time_str = parts[4].split(".")[0]
                version = f"{date_str}_{time_str}"
            elif basename == "training_val_loss.png":
                version = "Latest"
            else:
                version = "Unknown"
                
            graphs.append({
                "filename": basename,
                "version": version,
                "path": f"/api/training/loss_graphs/{basename}"
            })
            
        # Sort so Latest is first, then timestamped ones descending
        graphs.sort(key=lambda x: (x["version"] != "Latest", x["version"]), reverse=True)
            
        return {"status": "ok", "graphs": graphs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/training/loss_graphs/{filename}")
async def get_loss_graph_file(filename: str):
    import os
    from fastapi.responses import FileResponse
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(backend_dir, "data", "models")
    file_path = os.path.join(models_dir, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

@app.get("/api/training/pending")
async def get_training_pending(limit: int = 50):
    from training_db import training_db
    try:
        pending = training_db.get_pending(limit)
        return {"status": "ok", "samples": pending}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/training/needs_screenshot")
async def get_needs_screenshot(symbol: str, timeframe: str):
    from training_db import training_db
    try:
        needs = training_db.get_needs_screenshot(symbol, timeframe)
        return {"status": "ok", "boxes": needs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/training/upload_screenshot")
async def upload_screenshot(data: dict):
    from training_db import training_db
    try:
        box_id = data.get("box_id")
        b64 = data.get("screenshot_b64")
        if not box_id or not b64:
            raise HTTPException(status_code=400, detail="Missing box_id or screenshot_b64")
        training_db.save_screenshot(box_id, b64)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/training/undo")
async def undo_training_label(data: dict):
    from training_db import training_db
    try:
        box_id = data.get("box_id")
        if not box_id:
            raise HTTPException(status_code=400, detail="Missing box_id")
        training_db.reset_box(box_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/training/stats")
async def get_training_stats():
    import sqlite3
    try:
        with sqlite3.connect("training_set.db", timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            res = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'LABELED' OR status = 'ANALYZED' THEN 1 ELSE 0 END) as labeled
                FROM review_queue
            """).fetchone()
            return {"status": "ok", "stats": dict(res)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/training/lessons")
async def get_training_lessons():
    import sqlite3, hashlib
    try:
        with sqlite3.connect("training_set.db", timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT box_id, gemini_analysis, created_at FROM review_queue
                WHERE status = 'ANALYZED'
                  AND gemini_analysis IS NOT NULL
                  AND gemini_analysis NOT LIKE '%API Error%'
                  AND gemini_analysis NOT LIKE '%429%'
                  AND length(gemini_analysis) > 50
                ORDER BY created_at DESC LIMIT 20
            """)
            rows = cursor.fetchall()
            lessons = []
            seen_hashes = set()  # deduplicate near-identical content
            for r in rows:
                raw = r['gemini_analysis'] or ''
                # Take first paragraph (before LOGIC separator)
                main = raw.split('\n\n---\n')[0].strip()
                if not main:
                    continue
                # Content hash (first 120 chars) for dedup
                content_key = hashlib.md5(main[:120].encode()).hexdigest()
                if content_key in seen_hashes:
                    continue
                seen_hashes.add(content_key)
                lessons.append({
                    'id': r['box_id'],
                    'text': main[:400] if len(main) > 400 else main,
                    'created_at': r['created_at'] or '',
                    'hash': content_key,
                })
                if len(lessons) >= 10:
                    break
            return {"status": "ok", "lessons": lessons}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/training/label")
async def submit_training_label(data: dict):
    from training_db import training_db
    from gemini_trainer import gemini_trainer
    try:
        box_id = data.get("box_id")
        user_box = data.get("user_box") # {timeStart, timeEnd, priceHigh, priceLow}
        is_skip = data.get("is_skip", False)

        if not box_id:
            raise HTTPException(status_code=400, detail="Missing box_id")
            
        if is_skip:
            # Check if this is a hard sample
            try:
                import json
                hard_samples_path = os.path.join("data", "models", "hard_samples.json")
                if os.path.exists(hard_samples_path):
                    with open(hard_samples_path, "r") as f:
                        hard_samples = json.load(f)
                        hard_ids = set(s["box_id"] for s in hard_samples)
                        if str(box_id) in hard_ids:
                            # Promote to ANALYZED even if skipped, so it moves out of loss samples
                            training_db.update_label(box_id, [])
                            return {"status": "ok"}
            except Exception as e:
                print(f"Error checking hard samples on skip: {e}")
                
            training_db.skip_box(box_id)
            return {"status": "ok"}

        if not user_box:
            raise HTTPException(status_code=400, detail="Missing user_box")

        # Normalize: always store user_box as a list regardless of how many boxes drawn
        if isinstance(user_box, dict):
            user_box = [user_box]
            
            
        count = training_db.update_label(box_id, user_box)
        
        # AI Rule Evolution Agent Hook
        try:
            import sqlite3
            with sqlite3.connect("training_set.db", timeout=30.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT symbol, timeframe, original_meta FROM review_queue WHERE box_id=?", (box_id,))
                row = cursor.fetchone()
                if row:
                    import json
                    orig_meta = json.loads(row["original_meta"]) if row["original_meta"] else {}
                    
                    original_box = {
                        "start": orig_meta.get("start", 0),
                        "end": orig_meta.get("end", 0),
                        "top": float(orig_meta.get("priceHigh", 0)),
                        "bottom": float(orig_meta.get("priceLow", 0)),
                        "type": orig_meta.get("type", "LOOSE"),
                        "score": float(orig_meta.get("score", 0.0))
                    }
                    
                    user_box_mapped = None
                    if user_box and len(user_box) > 0:
                        u_box = user_box[0]
                        user_box_mapped = {
                            "start": u_box.get("start", original_box["start"]),
                            "end": u_box.get("end", original_box["end"]),
                            "top": float(u_box.get("priceHigh", original_box["top"])),
                            "bottom": float(u_box.get("priceLow", original_box["bottom"]))
                        }
                        
                    status = 'edited' if user_box_mapped else 'validated'
                    
                    learner = UserStyleLearner()
                    learner.record_feedback(
                        symbol=row["symbol"],
                        timeframe=row["timeframe"],
                        original_box=original_box,
                        user_box=user_box_mapped,
                        status=status
                    )
        except Exception as e:
            logger.warning(f"Failed to record feedback for rule evolution: {e}")
        
        # Trigger Gemini Analysis in background
        threading.Thread(target=gemini_trainer.process_and_save, args=(box_id,), daemon=True).start()

        # Automatic training disabled - user requested manual only
        
        return {"status": "ok", "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/training/nn_status")
async def get_nn_status():
    from training_db import training_db
    try:
        status = training_db.get_training_status()
        return {"status": "ok", "data": status}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/training/skip")
async def skip_training_sample(data: dict):
    from training_db import training_db
    try:
        box_id = data.get("box_id")
        if not box_id:
            raise HTTPException(status_code=400, detail="Missing box_id")
        training_db.skip_box(box_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/training/retrain_nn")
async def manual_retrain_nn():
    """Trigger the PyTorch CNN training manually."""
    try:
        from ml.train_nn import train_async
        train_async(force=True)
        

            
        return {"status": "triggered"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/training/training_progress_nn")
async def get_nn_training_progress():
    """Return the real-time logs and loss of the CNN trainer."""
    try:
        from ml.train_nn import TRAINING_STATE
        return TRAINING_STATE
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/training/stop_nn")
async def stop_nn_training():
    """Request to stop active NN training."""
    try:
        from ml.train_nn import TRAINING_STATE
        if not TRAINING_STATE.get("is_training", False):
            return {"status": "not_running"}
            
        TRAINING_STATE["stop_requested"] = True
        return {"status": "stop_requested"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/training/sync")
async def sync_training_queue():
    """
    Force-sync all currently detected consolidations into the training DB.
    Allows the user to fetch 'fresh' boxes from the live chart.
    """
    try:
        from training_db import training_db
        # 1. Get all current zones across all timeframes
        res = get_consolidations_all()
        if res.get("status") != "ok":
            return {"status": "error", "message": "Failed to fetch live zones"}
        
        zones = res.get("zones", [])
        synced_count = 0
        
        # 2. Upsert each zone into the DB
        # Note: In a real scenario, we might need candle context too.
        # But get_consolidations_all doesn't return full context.
        # We rely on the fact that these zones will be sampled with context 
        # when the chart is actually viewed or gap-filled.
        # However, for an immediate 'Sync', we can just upsert the metadata.
        for z in zones:
            # training_db.upsert_box expects (zone_data, context_candles)
            # We pass empty context for now; it will be filled by background sampling if missing.
            training_db.upsert_box(z, [])
            synced_count += 1
            
        return {"status": "ok", "synced": synced_count}
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/nn/refined_zones")
async def get_nn_refined_zones(symbol: str = "EURUSD", timeframe: str = "5m"):
    """Return consolidation zones enriched with NN-predicted refined box coordinates."""
    try:
        import pandas as pd
        from ml.nn_scorer import predict_box, is_nn_ready, load_nn_model
        from indicators.consolidation import consolidation_boxes

        # Load model if not yet loaded
        if not is_nn_ready():
            load_nn_model()

        raw_candles = storage.get_candles("OANDA", symbol, timeframe, count=1000)
        if not raw_candles:
            return []

        zones_with_nn = []
        try:
            df = pd.DataFrame(raw_candles)
            if 'time' in df.columns:
                use_timestamp = timeframe in ["1m", "5m", "15m", "1h", "4h"]
                if use_timestamp:
                    first_t = df['time'].iloc[0]
                    try:
                        first_t_num = float(first_t)
                        unit = 'ms' if first_t_num > 1e11 else 's'
                        df['time'] = pd.to_datetime(df['time'], unit=unit)
                    except (ValueError, TypeError):
                        df['time'] = pd.to_datetime(df['time'], unit='s')
                else:
                    df['time'] = pd.to_datetime(df['time'])
                df.set_index('time', inplace=True)
            
            raw_zones = consolidation_boxes(df)[-20:].to_dict('records')
        except Exception as e:
            logger.warning(f"[nn_zones] consolidation_boxes failed: {e}")
            return []

        for zone in raw_zones:
            nn_box = None
            if is_nn_ready():
                try:
                    z_idx_start = int(zone.get('start', 0))
                    z_idx_end   = int(zone.get('end', 0))
                    
                    # Align with training: box ends ~30 candles before the window end
                    ctx_end_idx   = min(len(df) - 1, z_idx_end + 30)
                    ctx_start_idx = max(0, ctx_end_idx - 100)
                    
                    ohlc_slice_df = df.iloc[ctx_start_idx : ctx_end_idx].copy()
                    ohlc_slice_df.index.name = 'time'
                    ohlc_slice = ohlc_slice_df.reset_index().to_dict('records')
                    
                    for c in ohlc_slice:
                        if 'time' in c:
                            # Handle both datetime and other types
                            if hasattr(c['time'], 'timestamp'):
                                c['time'] = c['time'].timestamp()
                            else:
                                try:
                                    import pandas as pd
                                    c['time'] = pd.to_datetime(c['time']).timestamp()
                                except: pass
                    
                    if len(ohlc_slice) >= 10:
                        nn_box = predict_box(ohlc_slice)
                except Exception as e:
                    logger.debug(f"[nn_zones] predict_box failed for zone at {zone.get('start')}: {e}")
            
            # Map start/end/top/bottom to frontend names for the base zone too
            try:
                start_ts = df.index[int(zone['start'])].timestamp() * 1000
                end_ts   = df.index[int(zone['end'])].timestamp() * 1000
                zone_mapped = {
                    'box_id': f"nn_base_{int(zone['start'])}",
                    'timeStart': start_ts,
                    'timeEnd': end_ts,
                    'priceHigh': zone['top'],
                    'priceLow': zone['bottom'],
                    'type': zone['type'],
                    'score': zone['score'],
                    'nn_box': nn_box
                }
                zones_with_nn.append(zone_mapped)
            except:
                pass

        return zones_with_nn
    except Exception as e:
        logger.error(f"[nn_zones] endpoint failed: {e}")
        return []


# ── Pattern Memory Endpoints (Phase 6) ───────────────────────────────────────

@app.get("/api/patterns")
async def list_patterns(
    symbol:    Optional[str] = Query(None, description="Filter by symbol, e.g. EURUSD"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe, e.g. 15m"),
    direction: Optional[str] = Query(None, description="Filter by breakout direction: UP, DOWN, or NONE"),
    min_quality: float = Query(0.0, description="Minimum quality score"),
    limit: int = Query(100, le=500, description="Max rows to return"),
    offset: int = Query(0, description="Pagination offset"),
):
    """
    Return a list of patterns from pattern_memory.db as compact summaries
    (no embedding blobs). Supports filtering by symbol, timeframe, direction,
    and minimum quality score.
    """
    try:
        from ml2.pattern_memory.pattern_db import PatternMemoryDB, EMBEDDING_VERSION
        db = PatternMemoryDB()

        clauses = ["embedding_version = ?"]
        params: list = [EMBEDDING_VERSION]

        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        if direction:
            clauses.append("breakout_direction = ?")
            params.append(direction.upper())
        if min_quality > 0:
            clauses.append("quality_score >= ?")
            params.append(min_quality)

        where = " AND ".join(clauses)
        count_params = list(params)   # snapshot before appending limit/offset
        params += [limit, offset]

        with db._conn() as conn:
            rows = conn.execute(f"""
                SELECT
                    pattern_id, box_id, symbol, exchange, timeframe,
                    box_time_start, box_time_end, price_high, price_low,
                    box_width_candles, quality_score, is_valid,
                    breakout_direction, breakout_strength, breakout_confirmed,
                    future_return_10, future_return_20, future_return_50, future_return_100,
                    mfe, mae, time_to_breakout, post_breakout_follow,
                    atr_at_box_end, box_height_atr, source, human_reviewed, created_at
                FROM patterns
                WHERE {where}
                ORDER BY box_time_end DESC
                LIMIT ? OFFSET ?
            """, params).fetchall()

            total = conn.execute(
                f"SELECT COUNT(*) FROM patterns WHERE {where}",
                count_params
            ).fetchone()[0]

        patterns = []
        for r in rows:
            d = dict(r)
            d["win"] = (d.get("future_return_20") or 0) > 0.0015
            d["loss"] = (d.get("future_return_20") or 0) < -0.0015
            patterns.append(d)

        return {"patterns": patterns, "total": total, "limit": limit, "offset": offset}

    except Exception as e:
        logger.error(f"[/api/patterns] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pattern/candles")
async def get_pattern_candles(
    symbol:    str = Query(...),
    timeframe: str = Query(...),
    time_start: int = Query(..., description="Box start time in milliseconds"),
    time_end:   int = Query(..., description="Box end time in milliseconds"),
    pre_candles: int = Query(60, description="Extra candles before box start"),
    post_candles: int = Query(40, description="Extra candles after box end"),
):
    """
    Return OHLCV candles around a pattern box window for mini-chart display.
    """
    try:
        tf_secs = TF_INTERVAL_SECS.get(timeframe, 900)
        start_sec = time_start // 1000
        end_sec   = time_end   // 1000
        query_start = start_sec - pre_candles * tf_secs
        query_end   = end_sec   + post_candles * tf_secs

        sym_bare = symbol.split(":")[-1] if ":" in symbol else symbol
        candles = []
        for sym in (symbol, sym_bare):
            rows = candle_db.get_candles("OANDA", sym, timeframe, start_ts=query_start, end_ts=query_end)
            if rows:
                candles = [{"time": r["ts"], "open": r["open"], "high": r["high"],
                             "low": r["low"], "close": r["close"], "volume": r.get("volume", 0)}
                           for r in rows]
                break

        return {
            "candles": candles,
            "box_start_sec": start_sec,
            "box_end_sec":   end_sec,
        }
    except Exception as e:
        logger.error(f"[/api/pattern/candles] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pattern/stats")
async def get_pattern_stats():
    """Return Pattern Memory DB and FAISS index health statistics."""
    try:
        from ml2.pattern_memory.pattern_db import PatternMemoryDB
        from ml2.pattern_memory.similarity_engine import get_engine
        db = PatternMemoryDB()
        engine = get_engine()
        stats = db.get_stats()
        stats["faiss_index_size"] = engine.size
        stats["faiss_ready"] = engine.size > 0
        return stats
    except Exception as e:
        logger.error(f"[pattern/stats] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pattern/intelligence")
async def get_pattern_intelligence(
    symbol:    str = Query("EURUSD"),
    timeframe: str = Query("15m"),
    horizon:   int = Query(20, description="Return horizon in candles: 10, 20, 50, or 100"),
    top_k:     int = Query(50, description="Number of FAISS neighbours to retrieve"),
):
    """
    For the given symbol+timeframe, extract a TimeFM embedding from the most
    recent candles and return a full PatternIntelligence report comparing this
    pattern against all historical patterns in the Pattern Memory DB.
    """
    try:
        from ml2.timesfm_predictor import TimesFMPredictor
        from ml2.pattern_memory.pattern_db import PatternMemoryDB
        from ml2.pattern_memory.similarity_engine import get_engine
        from ml2.pattern_memory.outcome_intelligence import OutcomeIntelligence

        # 1. Resolve candles from RAM storage
        raw_candles = storage.get_candles("OANDA", symbol, timeframe, count=512)
        if not raw_candles or len(raw_candles) < 10:
            raise HTTPException(status_code=400, detail=f"Not enough candles for {symbol}/{timeframe}")

        # Normalise candle dicts
        candles = [{k.lower(): v for k, v in c.items()} for c in raw_candles if isinstance(c, dict)]

        # 2. Lazy-load or reuse TimesFM predictor
        from ml2 import inference as _inf
        predictor = _inf.timesfm_predictor
        if predictor is None:
            raise HTTPException(status_code=503, detail="TimesFM model not loaded")

        # 3. Get embedding
        embedding = predictor.get_embedding(candles)

        # 4. FAISS search
        engine = get_engine()
        if engine.size == 0:
            raise HTTPException(status_code=503, detail="FAISS index not ready yet")

        top_k_results = engine.search(embedding, k=top_k)
        if not top_k_results:
            return {"error": "No similar patterns found", "n_matches": 0}

        pids   = [pid for pid, _ in top_k_results]
        scores = [score for _, score in top_k_results]

        # 5. Hydrate records
        db      = PatternMemoryDB()
        matches = db.get_patterns_by_ids(pids)

        # 6. Compute outcome intelligence
        intel      = OutcomeIntelligence()
        report     = intel.compute(matches, scores, horizon=horizon)
        result     = report.to_dict()
        result["symbol"]    = symbol
        result["timeframe"] = timeframe
        result["n_candles_used"] = len(candles)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[pattern/intelligence] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)