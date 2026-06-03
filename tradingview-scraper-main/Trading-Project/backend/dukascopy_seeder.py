"""
dukascopy_seeder.py — Seed historical OHLCV data from Dukascopy's binary data feed.

Uses the real Dukascopy datafeed (datafeed.dukascopy.com), NOT the deprecated
freeserv widget API (freeserv.dukascopy.com/2.0/?path=chart/json which returns []).

Data source: BID_candles_min_1.bi5 files — LZMA-compressed 1-minute candle files.
  URL: https://datafeed.dukascopy.com/datafeed/{INSTRUMENT}/{YEAR}/{MONTH_0IDX:02d}/{DAY:02d}/BID_candles_min_1.bi5
  Month is 0-indexed (January=00, December=11).
  Each record: 24 bytes, struct ">IIIIIf"
    - ms_from_day_start (uint32): milliseconds offset from 00:00:00 UTC
    - open  (uint32): price × point_multiplier (e.g. 100000 for 5-decimal pairs)
    - high  (uint32)
    - low   (uint32)
    - close (uint32)
    - volume (float32): in millions of units

Seed strategy (per pair) — HISTORICAL ONLY, not recent/live data:
  1d  — 5 years of daily bars       (aggregated from 1m files)
  1h  — 6 months of hourly bars     (aggregated from 1m files)

5m / 1m / live data are handled by the TradingView WebSocket delta-engine.

Idempotent: any series that already has >= MIN_ROWS is skipped entirely.
"""

import lzma
import struct
import time
import logging
import requests
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# ── HTTP headers — mimic a browser to avoid 403 ───────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.dukascopy.com/",
    "Accept": "*/*",
}

BASE_URL = "https://datafeed.dukascopy.com/datafeed"

# ── Instrument map ─────────────────────────────────────────────────────────────
# Maps our symbol → (Dukascopy instrument name, pip multiplier)
# pip multiplier: the integer OHLC values in bi5 files must be divided by this
# to get the actual price.
INSTRUMENTS: Dict[str, Tuple[str, int]] = {
    "EURUSD": ("EURUSD", 100_000),   # 5 decimal places
    "XAUUSD": ("XAUUSD",   1_000),   # 3 decimal places (decimally scaled raw price)
}

# ── Seed plan (historical only) ────────────────────────────────────────────────
# Tuple: (timeframe, lookback_days, min_rows_to_skip)
# Keep lookback dates well in the past — recent/live data is handled by TV WS.
SEED_PLAN = [
    ("1d", 5 * 365, 300),   # 5 years daily    — skip if >= 300 rows
    ("1h", 180,     500),   # 6 months hourly  — skip if >= 500 rows
]

# Number of past days to leave out — don't seed data from the last N days
# (recent data is managed by the live delta-engine, not Dukascopy)
RECENCY_CUTOFF_DAYS = 3

# Struct format for one 1-minute candle record (24 bytes, big-endian)
# ms_offset(uint32) open(uint32) high(uint32) low(uint32) close(uint32) volume(float32)
_RECORD_FMT  = ">IIIIIf"
_RECORD_SIZE = struct.calcsize(_RECORD_FMT)   # 24 bytes

# Polite delay between HTTP requests (seconds)
REQUEST_DELAY = 0.3


# ─────────────────────────────────────────────────────────────────────────────
# Binary feed helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_day_1m(instrument: str, day: date) -> List[dict]:
    """
    Download and decode one day's worth of 1-minute candles for `instrument`.

    Returns a list of candle dicts with keys:
        ts (unix timestamp, seconds UTC), open, high, low, close, volume
    Returns an empty list if the file is missing (404) or malformed.
    """
    month_0 = day.month - 1   # Dukascopy uses 0-indexed months
    url = (
        f"{BASE_URL}/{instrument}"
        f"/{day.year}/{month_0:02d}/{day.day:02d}"
        f"/BID_candles_min_1.bi5"
    )
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        if resp.status_code == 404:
            return []   # Weekend or holiday — normal
        resp.raise_for_status()
        if not resp.content:
            return []
    except requests.Timeout:
        logger.warning("[dukascopy] Timeout downloading %s %s", instrument, day)
        return []
    except Exception as exc:
        logger.warning("[dukascopy] Error downloading %s %s: %s", instrument, day, exc)
        return []

    try:
        raw = lzma.decompress(resp.content)
    except lzma.LZMAError as exc:
        logger.warning("[dukascopy] LZMA decode failed %s %s: %s", instrument, day, exc)
        return []

    if len(raw) % _RECORD_SIZE != 0:
        logger.warning(
            "[dukascopy] Unexpected byte count %d (not divisible by %d) for %s %s",
            len(raw), _RECORD_SIZE, instrument, day,
        )
        return []

    # day start as UTC unix timestamp
    day_start_ts = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())

    candles = []
    n_records = len(raw) // _RECORD_SIZE
    for i in range(n_records):
        ms_off, o_raw, h_raw, l_raw, c_raw, vol = struct.unpack_from(_RECORD_FMT, raw, i * _RECORD_SIZE)
        # Skip Dukascopy placeholder rows (o==h==l==c and vol==0)
        if o_raw == h_raw == l_raw == c_raw and vol == 0.0:
            continue
        candles.append({
            "ms_off": ms_off,
            "ts":     day_start_ts + ms_off // 1000,
            "open_raw":  o_raw,
            "high_raw":  h_raw,
            "low_raw":   l_raw,
            "close_raw": c_raw,
            "volume":    float(vol),
        })
    return candles


def _decode_prices(candles_raw: List[dict], pip_mult: int) -> List[dict]:
    """Convert raw integer OHLC values to actual prices."""
    out = []
    for c in candles_raw:
        out.append({
            "ts":     c["ts"],
            "open":   c["open_raw"]  / pip_mult,
            "high":   c["high_raw"]  / pip_mult,
            "low":    c["low_raw"]   / pip_mult,
            "close":  c["close_raw"] / pip_mult,
            "volume": c["volume"],
        })
    return out


def _aggregate_to_1h(day_1m: List[dict], pip_mult: int) -> List[dict]:
    """
    Aggregate 1-minute candles into 1-hour candles.
    Returns candles keyed by the hour's start timestamp.
    """
    buckets: Dict[int, dict] = {}
    for c in day_1m:
        # Round down to the nearest hour (ts is already in seconds)
        hour_ts = c["ts"] - (c["ts"] % 3600)
        if hour_ts not in buckets:
            buckets[hour_ts] = {
                "ts":     hour_ts,
                "open_raw":  c["open_raw"],
                "high_raw":  c["high_raw"],
                "low_raw":   c["low_raw"],
                "close_raw": c["close_raw"],
                "volume":    c["volume"],
            }
        else:
            b = buckets[hour_ts]
            b["high_raw"]  = max(b["high_raw"],  c["high_raw"])
            b["low_raw"]   = min(b["low_raw"],   c["low_raw"])
            b["close_raw"] = c["close_raw"]
            b["volume"]   += c["volume"]
    return _decode_prices(sorted(buckets.values(), key=lambda x: x["ts"]), pip_mult)


def _aggregate_to_1d(day_1m: List[dict], pip_mult: int, day: date) -> Optional[dict]:
    """
    Aggregate an entire day's 1-minute candles into a single daily candle.
    Requires at least 60 valid 1-min bars to be considered a real trading day.
    Returns None if no/insufficient data (weekend, holiday, etc.).
    """
    MIN_BARS = 60  # at least 1 hour of 1-min data for a valid trading day
    if len(day_1m) < MIN_BARS:
        return None
    day_start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    o_raw = day_1m[0]["open_raw"]
    h_raw = max(c["high_raw"]  for c in day_1m)
    l_raw = min(c["low_raw"]   for c in day_1m)
    c_raw = day_1m[-1]["close_raw"]
    vol   = sum(c["volume"] for c in day_1m)
    return {
        "ts":     day_start,
        "open":   o_raw / pip_mult,
        "high":   h_raw / pip_mult,
        "low":    l_raw / pip_mult,
        "close":  c_raw / pip_mult,
        "volume": vol,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main fetch function
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    lookback_days: int,
    candle_db = None,
    exchange: str = "OANDA"
) -> List[dict]:
    """
    Download historical OHLCV data from Dukascopy's binary feed.

    - Checks local SQLite database for existing data to avoid redundant downloads.
    - Downloads daily BID_candles_min_1.bi5 files for each day in the range.
    - Aggregates 1-minute bars to 1h or 1d as requested.
    - Stops RECENCY_CUTOFF_DAYS before today so we never overlap with live data.
    - Returns deduplicated list of candles sorted ascending by timestamp.
    """
    entry = INSTRUMENTS.get(symbol)
    if not entry:
        logger.warning("[dukascopy] No mapping for symbol '%s'", symbol)
        return []
    instrument, pip_mult = entry

    if timeframe not in ("1d", "1h"):
        logger.warning(
            "[dukascopy] Timeframe '%s' not supported — Dukascopy seeder only handles "
            "historical 1h/1d bars. Recent/live data is handled by the TV delta-engine.",
            timeframe,
        )
        return []

    # Date range — stop well before today (live data is from TV WebSocket)
    today    = datetime.now(timezone.utc).date()
    end_date = today - timedelta(days=RECENCY_CUTOFF_DAYS)
    start_date = today - timedelta(days=lookback_days)

    existing_timestamps = set()
    if candle_db:
        try:
            conn = candle_db._conn()
            rows = conn.execute(
                "SELECT ts FROM candles WHERE exchange=? AND symbol=? AND timeframe=?",
                (exchange, symbol, timeframe)
            ).fetchall()
            existing_timestamps = {r[0] for r in rows}
        except Exception as e:
            logger.error("[dukascopy] Error querying existing timestamps: %s", e)

    logger.info(
        "[dukascopy] Fetching %s [%s] %s → %s (%d days, %d existing checked)",
        symbol, timeframe, start_date, end_date,
        (end_date - start_date).days, len(existing_timestamps),
    )

    all_1h: List[dict] = []
    all_1d: List[dict] = []

    current = start_date
    days_fetched = 0
    days_skipped = 0   # weekends / holidays / already in db
    db_skipped = 0

    while current <= end_date:
        # Check if this day is already in the database
        day_start_ts = int(datetime(current.year, current.month, current.day, tzinfo=timezone.utc).timestamp())
        if timeframe == "1d":
            if day_start_ts in existing_timestamps:
                db_skipped += 1
                current += timedelta(days=1)
                continue
        elif timeframe == "1h":
            # Check if any hour within this day is in existing_timestamps
            day_has_data = any(
                (day_start_ts + hour * 3600) in existing_timestamps
                for hour in range(24)
            )
            if day_has_data:
                db_skipped += 1
                current += timedelta(days=1)
                continue

        raw_1m = _fetch_day_1m(instrument, current)
        time.sleep(REQUEST_DELAY)

        if raw_1m:
            days_fetched += 1
            if timeframe == "1h":
                all_1h.extend(_aggregate_to_1h(raw_1m, pip_mult))
            else:  # 1d
                daily = _aggregate_to_1d(raw_1m, pip_mult, current)
                if daily:
                    all_1d.append(daily)
        else:
            days_skipped += 1   # 404 = weekend/holiday, expected

        current += timedelta(days=1)

    result = all_1h if timeframe == "1h" else all_1d

    # Deduplicate by timestamp
    seen: dict = {}
    for c in result:
        seen[c["ts"]] = c
    result = sorted(seen.values(), key=lambda x: x["ts"])

    logger.info(
        "[dukascopy] ✓ %s [%s]: %d new bars fetched (%d trading days, %d skipped, %d db-skipped)",
        symbol, timeframe, len(result), days_fetched, days_skipped, db_skipped,
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points (same API as before — server.py needs no changes)
# ─────────────────────────────────────────────────────────────────────────────

def seed_missing_pairs(candle_db, exchange: str = "OANDA") -> None:
    """
    Iterate over all pairs × SEED_PLAN timeframes.
    For each series that doesn't have enough rows, download historical data
    from Dukascopy's binary feed and insert into candle_db.

    Safe to call in a background thread — fully idempotent.
    """
    logger.info("=== Dukascopy seeder starting for %d pairs ===", len(INSTRUMENTS))

    for symbol in INSTRUMENTS:
        for timeframe, lookback_days, min_rows in SEED_PLAN:
            existing = candle_db.count(exchange, symbol, timeframe)

            if existing >= min_rows:
                logger.info(
                    "[dukascopy] Skip %s:%s [%s] — already %d/%d rows",
                    exchange, symbol, timeframe, existing, min_rows,
                )
                continue

            logger.info(
                "[dukascopy] Seeding %s:%s [%s] (have %d, need %d)",
                exchange, symbol, timeframe, existing, min_rows,
            )

            candles = fetch_ohlcv(symbol, timeframe, lookback_days, candle_db, exchange)
            if candles:
                candle_db.upsert_candles(exchange, symbol, timeframe, candles)
                stored = candle_db.count(exchange, symbol, timeframe)
                logger.info(
                    "[dukascopy] ✓ %s:%s [%s] → %d rows in DB",
                    exchange, symbol, timeframe, stored,
                )
            else:
                logger.warning(
                    "[dukascopy] ✗ No data returned for %s:%s [%s]",
                    exchange, symbol, timeframe,
                )

    logger.info("=== Dukascopy seeder complete ===")


def seed_single_symbol(candle_db, symbol: str, exchange: str = "OANDA",
                       force: bool = False) -> None:
    """
    Seed a single symbol on-demand (e.g. from /api/fetch-symbol endpoint).
    force=True re-downloads even if min_rows already met.
    """
    if symbol not in INSTRUMENTS:
        logger.warning("[dukascopy] seed_single_symbol: '%s' not in instrument map", symbol)
        return

    logger.info("[dukascopy] On-demand seed: %s", symbol)
    for timeframe, lookback_days, min_rows in SEED_PLAN:
        existing = candle_db.count(exchange, symbol, timeframe)
        if not force and existing >= min_rows:
            logger.info(
                "[dukascopy] On-demand skip %s:%s [%s] — %d rows exist",
                exchange, symbol, timeframe, existing,
            )
            continue

        candles = fetch_ohlcv(symbol, timeframe, lookback_days, candle_db, exchange)
        if candles:
            candle_db.upsert_candles(exchange, symbol, timeframe, candles)
            logger.info(
                "[dukascopy] On-demand ✓ %s:%s [%s] → %d rows",
                exchange, symbol, timeframe,
                candle_db.count(exchange, symbol, timeframe),
            )
