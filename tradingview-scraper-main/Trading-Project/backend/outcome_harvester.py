"""
Outcome Harvester — Phase 0
Reads LABELED/ANALYZED boxes from training_set.db,
looks up future candles from candles.db,
and computes outcome labels (future_return, MFE, MAE, breakout_direction).

Usage:
  python outcome_harvester.py --check-coverage
  python outcome_harvester.py --harvest
  python outcome_harvester.py --harvest --limit 100
"""
import os
import sys
import json
import sqlite3
import argparse
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
TRAINING_DB  = os.path.join(BACKEND_DIR, "training_set.db")
DATA_DIR     = os.path.join(BACKEND_DIR, "data")

# candle storage may be candles.db or candles.sqlite depending on pipeline version
_CANDLES_CANDIDATES = [
    os.path.join(BACKEND_DIR, "..", "data", "candles.db"),
    os.path.join(BACKEND_DIR, "..", "data", "candles.sqlite"),
    os.path.join(DATA_DIR, "candles.db"),
    os.path.join(DATA_DIR, "candles.sqlite"),
    os.path.join(BACKEND_DIR, "candles.db"),
    os.path.join(BACKEND_DIR, "candles.sqlite"),
]
CANDLES_DB = next(
    (p for p in _CANDLES_CANDIDATES if os.path.exists(p) and os.path.getsize(p) > 0),
    _CANDLES_CANDIDATES[0]
)



# ── Outcome configuration ──────────────────────────────────────────────────────
HORIZONS = [10, 20, 50, 100]   # candles forward for future_return_N
BREAKOUT_ATR_THRESHOLD = 0.5   # ATR multiples to classify breakout direction


def _get_candles_after(conn_candles, symbol, timeframe, after_ts, limit=200):
    """
    Fetch up to `limit` candles strictly after `after_ts` for (symbol, timeframe).
    Returns list of (ts, open, high, low, close) sorted ascending.
    """
    if after_ts > 100000000000:
        after_ts = after_ts // 1000
    # candles.db uses raw symbol without exchange prefix
    # Try exact match first, then strip exchange prefix
    for sym in (symbol, symbol.split(":")[-1] if ":" in symbol else symbol):
        cursor = conn_candles.execute("""
            SELECT ts, open, high, low, close
            FROM candles
            WHERE symbol = ? AND timeframe = ? AND ts > ?
            ORDER BY ts ASC
            LIMIT ?
        """, (sym, timeframe, int(after_ts), limit))

        rows = cursor.fetchall()
        if rows:
            return rows
    return []


def _atr(rows, period=14):
    """Compute ATR over the last `period` rows. Returns float or None."""
    if len(rows) < 2:
        return None
    trs = []
    for i in range(1, len(rows)):
        h = float(rows[i][2])
        l = float(rows[i][3])
        cp = float(rows[i-1][4])
        tr = max(h - l, abs(h - cp), abs(l - cp))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs[-period:]) / min(len(trs), period)


def compute_outcomes(box, ohlc_context, candles_after):
    """
    Compute outcome labels for a single pattern.

    Args:
        box: dict from review_queue (has priceHigh, priceLow, timeEnd, etc.)
        ohlc_context: list of dicts (OHLC candles inside/around the box)
        candles_after: list of (ts, o, h, l, c) tuples AFTER the box

    Returns:
        dict with all outcome fields, or None if insufficient data
    """
    if not candles_after or len(candles_after) < 2:
        return None

    # Reference close = close of last candle in ohlc_context (or close at box_end)
    try:
        ctx = ohlc_context if isinstance(ohlc_context, list) else json.loads(ohlc_context)
    except Exception:
        ctx = []

    if ctx:
        ref_close = float(ctx[-1].get("close", candles_after[0][4]))
    else:
        ref_close = float(candles_after[0][4])

    if ref_close == 0:
        return None

    price_high = float(box.get("priceHigh") or box.get("price_high") or 0)
    price_low  = float(box.get("priceLow")  or box.get("price_low")  or 0)

    # Future returns
    future_returns = {}
    for h in HORIZONS:
        if len(candles_after) >= h:
            future_close = float(candles_after[h - 1][4])
            future_returns[h] = (future_close - ref_close) / ref_close
        else:
            future_returns[h] = None

    # MFE and MAE (max favorable / adverse excursion) over next 50 candles
    n_mfe = min(50, len(candles_after))
    highs  = [float(r[2]) for r in candles_after[:n_mfe]]
    lows   = [float(r[3]) for r in candles_after[:n_mfe]]
    mfe_price = max(highs) if highs else ref_close
    mae_price = min(lows)  if lows  else ref_close

    # Compute ATR from context candles
    ctx_rows = [(None, c.get("open",0), c.get("high",0), c.get("low",0), c.get("close",0))
                for c in (ctx or [])] if ctx else []
    atr = _atr(ctx_rows) if ctx_rows else None
    if not atr:
        # Fallback: use box height / 3
        atr = (price_high - price_low) / 3 if (price_high - price_low) > 0 else None

    mfe = ((mfe_price - ref_close) / ref_close) if mfe_price else None
    mae = ((ref_close - mae_price) / ref_close) if mae_price else None
    mfe_atr = (mfe_price - ref_close) / atr if (atr and mfe_price) else None
    mae_atr = (ref_close - mae_price) / atr if (atr and mae_price) else None

    # Breakout direction — first time price breaks box boundaries
    breakout_direction = "NONE"
    breakout_strength  = None
    breakout_confirmed = 0
    time_to_breakout   = None
    post_breakout_follow = None

    for i, (ts, o, h, l, c) in enumerate(candles_after[:100]):
        h, l, c = float(h), float(l), float(c)
        if price_high > 0 and h > price_high:
            breakout_direction = "UP"
            time_to_breakout   = i + 1
            if atr and price_high > 0:
                breakout_strength = (h - price_high) / atr
            # Check follow-through: next 10 candles close above price_high
            if i + 11 <= len(candles_after):
                follow_closes = [float(candles_after[j][4]) for j in range(i+1, min(i+11, len(candles_after)))]
                n_above = sum(1 for fc in follow_closes if fc > price_high)
                breakout_confirmed = 1 if n_above >= 5 else 0
                if follow_closes:
                    post_breakout_follow = (follow_closes[-1] - price_high) / price_high
            break
        if price_low > 0 and l < price_low:
            breakout_direction = "DOWN"
            time_to_breakout   = i + 1
            if atr and price_low > 0:
                breakout_strength = (price_low - l) / atr
            if i + 11 <= len(candles_after):
                follow_closes = [float(candles_after[j][4]) for j in range(i+1, min(i+11, len(candles_after)))]
                n_below = sum(1 for fc in follow_closes if fc < price_low)
                breakout_confirmed = 1 if n_below >= 5 else 0
                if follow_closes:
                    post_breakout_follow = (price_low - follow_closes[-1]) / price_low
            break

    return {
        "future_return_10":      future_returns.get(10),
        "future_return_20":      future_returns.get(20),
        "future_return_50":      future_returns.get(50),
        "future_return_100":     future_returns.get(100),
        "mfe":                   mfe_atr,
        "mae":                   mae_atr,
        "breakout_direction":    breakout_direction,
        "breakout_strength":     breakout_strength,
        "breakout_confirmed":    breakout_confirmed,
        "time_to_breakout":      time_to_breakout,
        "post_breakout_follow":  post_breakout_follow,
        "atr_at_box_end":        atr,
        "box_height_atr":        (price_high - price_low) / atr if (atr and price_high > price_low) else None,
    }


def check_coverage():
    """Report how many labeled patterns have future candle data available."""
    if not os.path.exists(TRAINING_DB):
        log.error("Training DB not found: %s", TRAINING_DB)
        return
    if not os.path.exists(CANDLES_DB):
        log.error("Candles DB not found: %s", CANDLES_DB)
        return

    with sqlite3.connect(TRAINING_DB) as conn_train, \
         sqlite3.connect(CANDLES_DB)  as conn_candles:

        conn_train.row_factory = sqlite3.Row
        cursor = conn_train.execute("""
            SELECT box_id, symbol, timeframe, time_end, price_high, price_low
            FROM review_queue
            WHERE status IN ('LABELED', 'ANALYZED', 'PENDING_SCREENSHOT', 'PENDING')
            ORDER BY time_end ASC
        """)
        boxes = [dict(r) for r in cursor.fetchall()]

    log.info("Total boxes (LABELED/ANALYZED/PENDING_SCREENSHOT/PENDING): %d", len(boxes))


    covered = 0
    uncovered = []
    for b in boxes:
        sym = b["symbol"]
        tf  = b["timeframe"]
        ts  = b.get("time_end") or 0
        rows = _get_candles_after(conn_candles, sym, tf, ts, limit=5)
        if rows:
            covered += 1
        else:
            uncovered.append(b)

    log.info("Boxes WITH future candle data: %d / %d", covered, len(boxes))
    if uncovered:
        log.warning("Boxes WITHOUT future candle data: %d", len(uncovered))
        for b in uncovered[:5]:
            log.warning("  %s | %s | %s | ts=%s", b["box_id"], b["symbol"], b["timeframe"], b.get("time_end"))


def harvest(limit=None, overwrite=False):
    """
    For each LABELED/ANALYZED box:
      1. Look up future candles from candles.db
      2. Compute outcomes
      3. Write to training_set.db (new columns added if missing)

    Outcomes are stored back in review_queue via new columns:
      outcome_future_return_20, outcome_breakout_direction, outcome_mfe, outcome_mae,
      outcome_computed_at
    (Separate pattern_memory.db will be populated in Phase 3)
    """
    if not os.path.exists(TRAINING_DB):
        log.error("Training DB not found: %s", TRAINING_DB)
        return
    if not os.path.exists(CANDLES_DB):
        log.error("Candles DB not found: %s", CANDLES_DB)
        return

    # Ensure outcome columns exist in review_queue
    with sqlite3.connect(TRAINING_DB) as conn:
        cols_to_add = [
            ("outcome_future_return_10",     "REAL"),
            ("outcome_future_return_20",     "REAL"),
            ("outcome_future_return_50",     "REAL"),
            ("outcome_future_return_100",    "REAL"),
            ("outcome_mfe",                  "REAL"),
            ("outcome_mae",                  "REAL"),
            ("outcome_breakout_direction",   "TEXT"),
            ("outcome_breakout_strength",    "REAL"),
            ("outcome_breakout_confirmed",   "INTEGER"),
            ("outcome_time_to_breakout",     "INTEGER"),
            ("outcome_post_breakout_follow", "REAL"),
            ("outcome_atr_at_box_end",       "REAL"),
            ("outcome_box_height_atr",       "REAL"),
            ("outcome_computed_at",          "INTEGER"),
        ]
        existing = {row[1] for row in conn.execute("PRAGMA table_info(review_queue)")}
        for col_name, col_type in cols_to_add:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE review_queue ADD COLUMN {col_name} {col_type}")
        conn.commit()

    with sqlite3.connect(TRAINING_DB) as conn_train, \
         sqlite3.connect(CANDLES_DB)  as conn_candles:

        conn_train.row_factory = sqlite3.Row
        where_clause = "" if overwrite else "AND (outcome_computed_at IS NULL OR outcome_computed_at = '')"
        query = f"""
            SELECT *
            FROM review_queue
            WHERE status IN ('LABELED', 'ANALYZED', 'PENDING_SCREENSHOT', 'PENDING')
            {where_clause}
            ORDER BY time_end DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        boxes = [dict(r) for r in conn_train.execute(query).fetchall()]


    log.info("Boxes to process: %d", len(boxes))
    n_ok = 0
    n_skip = 0

    for i, box in enumerate(boxes):
        box_id     = box["box_id"]
        symbol     = box.get("symbol", "")
        timeframe  = box.get("timeframe", "")
        time_end   = box.get("time_end") or 0
        ohlc_ctx   = box.get("ohlc_context") or "[]"

        candles_after = _get_candles_after(conn_candles, symbol, timeframe, time_end, limit=120)

        outcomes = compute_outcomes(box, ohlc_ctx, candles_after)

        if outcomes is None:
            log.debug("[%d/%d] %s — insufficient future candles (skipped)", i+1, len(boxes), box_id)
            n_skip += 1
            continue

        import time as _time
        now = int(_time.time())

        with sqlite3.connect(TRAINING_DB) as conn:
            conn.execute("""
                UPDATE review_queue SET
                    outcome_future_return_10     = ?,
                    outcome_future_return_20     = ?,
                    outcome_future_return_50     = ?,
                    outcome_future_return_100    = ?,
                    outcome_mfe                  = ?,
                    outcome_mae                  = ?,
                    outcome_breakout_direction   = ?,
                    outcome_breakout_strength    = ?,
                    outcome_breakout_confirmed   = ?,
                    outcome_time_to_breakout     = ?,
                    outcome_post_breakout_follow = ?,
                    outcome_atr_at_box_end       = ?,
                    outcome_box_height_atr       = ?,
                    outcome_computed_at          = ?
                WHERE box_id = ?
            """, (
                outcomes["future_return_10"],
                outcomes["future_return_20"],
                outcomes["future_return_50"],
                outcomes["future_return_100"],
                outcomes["mfe"],
                outcomes["mae"],
                outcomes["breakout_direction"],
                outcomes["breakout_strength"],
                outcomes["breakout_confirmed"],
                outcomes["time_to_breakout"],
                outcomes["post_breakout_follow"],
                outcomes["atr_at_box_end"],
                outcomes["box_height_atr"],
                now,
                box_id,
            ))
            conn.commit()

        n_ok += 1
        if (i + 1) % 10 == 0:
            log.info("[%d/%d] Harvested %d, skipped %d", i+1, len(boxes), n_ok, n_skip)

    log.info("Done. Harvested: %d | Skipped (no future candles): %d", n_ok, n_skip)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outcome Harvester")
    parser.add_argument("--check-coverage", action="store_true", help="Report candle coverage")
    parser.add_argument("--harvest",        action="store_true", help="Compute and store outcomes")
    parser.add_argument("--limit",   type=int, default=None,  help="Max boxes to process")
    parser.add_argument("--overwrite", action="store_true",   help="Recompute already-harvested boxes")
    args = parser.parse_args()

    if args.check_coverage:
        check_coverage()
    elif args.harvest:
        harvest(limit=args.limit, overwrite=args.overwrite)
    else:
        parser.print_help()
