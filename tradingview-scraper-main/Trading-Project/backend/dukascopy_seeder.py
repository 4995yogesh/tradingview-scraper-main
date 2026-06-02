"""
dukascopy_seeder.py — Seed historical OHLCV data from Dukascopy's free public API.

Dukascopy provides free, no-auth OHLC data going back years for all major forex pairs.
API endpoint: https://freeserv.dukascopy.com/2.0/?path=chart/json

Seed strategy (per pair):
  1d  — 5 years of daily bars       (fast, one or two requests)
  1h  — 6 months of hourly bars     (intraday context for HTF synthesis)
  5m  — 30 days of 5-minute bars    (feeds the backend delta-engine)
  1m  — 7 days of 1-minute bars     (live HTF synthesis by delta-engine)

4h / 15m / 1w are NOT seeded — the backend synthesizes them from 1m/5m data automatically.

Idempotent: any series that already has >= MIN_ROWS is skipped entirely.
"""

import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Dukascopy instrument map ──────────────────────────────────────────────────
DUKASCOPY_INSTRUMENTS = {
    "EURUSD": "EUR/USD",
    "USDJPY": "USD/JPY",
    "GBPUSD": "GBP/USD",
    "USDCHF": "USD/CHF",
    "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD",
    "NZDUSD": "NZD/USD",
}

# ── Dukascopy interval values (minutes per bar) ───────────────────────────────
DUKA_INTERVAL = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
    "1w":  10080,
}

# ── Seed plan: (timeframe, lookback_days, min_rows_to_skip) ──────────────────
# A series is skipped if it already has >= min_rows_to_skip rows in the DB.
SEED_PLAN = [
    ("1d", 5 * 365, 300),   # 5 years daily    — skip if >= 300 rows
    ("1h", 180,     500),   # 6 months hourly  — skip if >= 500 rows
    ("5m", 30,      1_000), # 30 days 5m       — skip if >= 1000 rows
    ("1m", 7,       2_000), # 7 days 1m        — skip if >= 2000 rows
]

# Chunk size for pagination (days per Dukascopy request)
CHUNK_DAYS = 60

# Polite delay between HTTP requests (seconds)
REQUEST_DELAY = 0.8

BASE_URL = "https://freeserv.dukascopy.com/2.0/"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_chunk(instrument: str, interval_min: int,
                 from_dt: datetime, to_dt: datetime) -> List[dict]:
    """
    Fetch a single date-range chunk from Dukascopy.
    Returns a list of candle dicts: {ts (unix-sec), open, high, low, close, volume}.
    """
    fmt = "%Y-%m-%d %H:%M:%S.000"
    params = {
        "path":           "chart/json",
        "instrument":     instrument,
        "offer_side":     "B",          # bid side
        "interval":       str(interval_min),
        "splits":         "true",
        "time_direction": "next",
        "timezone":       "0",          # UTC
        "from":           from_dt.strftime(fmt),
        "to":             to_dt.strftime(fmt),
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("[dukascopy] Unexpected response type: %s", type(data))
            return []

        candles = []
        for bar in data:
            # Expected format: [timestamp_ms, open, high, low, close, volume]
            if not isinstance(bar, (list, tuple)) or len(bar) < 6:
                continue
            ts_ms = bar[0]
            o, h, l, c, v = float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4]), float(bar[5])
            ts_s = int(ts_ms) // 1000
            candles.append({"ts": ts_s, "open": o, "high": h, "low": l, "close": c, "volume": v})

        return candles

    except requests.Timeout:
        logger.warning("[dukascopy] Timeout fetching %s %d-min chunk %s → %s",
                       instrument, interval_min, from_dt.date(), to_dt.date())
        return []
    except Exception as exc:
        logger.warning("[dukascopy] Error fetching %s: %s", instrument, exc)
        return []


def fetch_ohlcv(symbol: str, timeframe: str, lookback_days: int) -> List[dict]:
    """
    Download OHLCV data from Dukascopy, paginating in CHUNK_DAYS windows.
    Returns deduplicated list of candles sorted ascending by timestamp.
    """
    instrument = DUKASCOPY_INSTRUMENTS.get(symbol)
    if not instrument:
        logger.warning("[dukascopy] No Dukascopy mapping for symbol '%s'", symbol)
        return []

    interval_min = DUKA_INTERVAL.get(timeframe)
    if interval_min is None:
        logger.warning("[dukascopy] No interval defined for timeframe '%s'", timeframe)
        return []

    # Align to midnight UTC
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt   = now
    start_dt = now - timedelta(days=lookback_days)

    logger.info("[dukascopy] Starting fetch: %s [%s] — %d days (%s → %s)",
                symbol, timeframe, lookback_days, start_dt.date(), end_dt.date())

    all_candles: List[dict] = []
    cursor = start_dt
    chunk_num = 0

    while cursor < end_dt:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end_dt)
        chunk_num += 1
        bars = _fetch_chunk(instrument, interval_min, cursor, chunk_end)
        if bars:
            all_candles.extend(bars)
            logger.debug("[dukascopy]   chunk #%d %s→%s: %d bars",
                         chunk_num, cursor.date(), chunk_end.date(), len(bars))
        cursor = chunk_end
        time.sleep(REQUEST_DELAY)

    # Deduplicate by timestamp (last write wins) then sort ascending
    seen: dict = {}
    for c in all_candles:
        seen[c["ts"]] = c
    result = sorted(seen.values(), key=lambda x: x["ts"])

    logger.info("[dukascopy] ✓ %s [%s]: %d total bars after dedup", symbol, timeframe, len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def seed_missing_pairs(candle_db, exchange: str = "OANDA") -> None:
    """
    Iterate over all 7 major pairs × SEED_PLAN timeframes.
    For each series that doesn't have enough rows, download from Dukascopy
    and insert into candle_db.

    This function is safe to call in a background thread — it is fully
    idempotent (skips any series that is already adequately populated).

    Args:
        candle_db: The CandleDB singleton from pipeline.data.db
        exchange:  Exchange label to use when storing (default "OANDA")
    """
    logger.info("=== Dukascopy seeder starting for %d pairs ===", len(DUKASCOPY_INSTRUMENTS))

    for symbol in DUKASCOPY_INSTRUMENTS:
        for timeframe, lookback_days, min_rows in SEED_PLAN:
            existing = candle_db.count(exchange, symbol, timeframe)

            if existing >= min_rows:
                logger.info("[dukascopy] Skip %s:%s [%s] — already %d/%d rows",
                            exchange, symbol, timeframe, existing, min_rows)
                continue

            logger.info("[dukascopy] Seeding %s:%s [%s] (have %d, need %d)",
                        exchange, symbol, timeframe, existing, min_rows)

            candles = fetch_ohlcv(symbol, timeframe, lookback_days)
            if candles:
                candle_db.upsert_candles(exchange, symbol, timeframe, candles)
                stored = candle_db.count(exchange, symbol, timeframe)
                logger.info("[dukascopy] ✓ %s:%s [%s] → %d rows in DB",
                            exchange, symbol, timeframe, stored)
            else:
                logger.warning("[dukascopy] ✗ No data returned for %s:%s [%s]",
                               exchange, symbol, timeframe)

    logger.info("=== Dukascopy seeder complete ===")


def seed_single_symbol(candle_db, symbol: str, exchange: str = "OANDA",
                       force: bool = False) -> None:
    """
    Seed a single symbol. Used by the /api/fetch-symbol on-demand endpoint.
    force=True bypasses the min_rows check and re-downloads everything.
    """
    if symbol not in DUKASCOPY_INSTRUMENTS:
        logger.warning("[dukascopy] seed_single_symbol: '%s' not in instrument map", symbol)
        return

    logger.info("[dukascopy] On-demand seed: %s", symbol)
    for timeframe, lookback_days, min_rows in SEED_PLAN:
        existing = candle_db.count(exchange, symbol, timeframe)
        if not force and existing >= min_rows:
            logger.info("[dukascopy] On-demand skip %s:%s [%s] — %d rows exist",
                        exchange, symbol, timeframe, existing)
            continue

        candles = fetch_ohlcv(symbol, timeframe, lookback_days)
        if candles:
            candle_db.upsert_candles(exchange, symbol, timeframe, candles)
            logger.info("[dukascopy] On-demand ✓ %s:%s [%s] → %d rows",
                        exchange, symbol, timeframe, candle_db.count(exchange, symbol, timeframe))
