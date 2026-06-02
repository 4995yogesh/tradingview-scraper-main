"""
Pattern Harvester — Phase 3
Offline CLI script to harvest patterns from training_set.db,
query context candles from candles.db, generate embeddings using TimeFM,
and populate pattern_memory.db.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import json
import logging
import argparse
from datetime import datetime
import numpy as np

# Force JAX CPU backend
os.environ["JAX_PLATFORMS"] = "cpu"

# Add backend and ml2 to paths
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, "ml2"))

from ml2.timesfm_predictor import TimesFMPredictor
from ml2.pattern_memory.pattern_db import PatternMemoryDB, PatternRecord
from ml2.pattern_memory.embedding_extractor import TimeFMEmbeddingExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def timeframe_to_seconds(tf: str) -> int:
    tf = tf.lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    if tf.endswith("w"):
        return int(tf[:-1]) * 86400 * 7
    return 900  # default 15m


def fetch_context_candles(conn_candles, symbol, timeframe, time_start_ms, time_end_ms, pre_candles=50):
    """
    Query candles from candles.db starting from pre_candles before time_start up to time_end.
    """
    start_sec = time_start_ms // 1000
    end_sec = time_end_ms // 1000
    duration_sec = timeframe_to_seconds(timeframe)
    
    query_start = start_sec - pre_candles * duration_sec
    
    # Try raw symbol and stripped symbol (without exchange prefix)
    for sym in (symbol, symbol.split(":")[-1] if ":" in symbol else symbol):
        cursor = conn_candles.execute("""
            SELECT ts, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (sym, timeframe, int(query_start), int(end_sec)))
        rows = cursor.fetchall()
        if rows:
            return [{
                "time": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5]
            } for r in rows]
    return []


def harvest(limit=None, overwrite=False):
    training_db_path = os.path.join(BACKEND_DIR, "training_set.db")
    
    # Locate candles database (non-empty)
    candles_candidates = [
        os.path.join(BACKEND_DIR, "..", "data", "candles.db"),
        os.path.join(BACKEND_DIR, "..", "data", "candles.sqlite"),
        os.path.join(BACKEND_DIR, "data", "candles.db"),
        os.path.join(BACKEND_DIR, "data", "candles.sqlite"),
    ]
    candles_db_path = next(
        (p for p in candles_candidates if os.path.exists(p) and os.path.getsize(p) > 0),
        None
    )
    
    if not os.path.exists(training_db_path):
        log.error(f"Training set DB not found: {training_db_path}")
        return
    if not candles_db_path:
        log.error("Active candles DB not found!")
        return

    log.info(f"Using training DB: {training_db_path}")
    log.info(f"Using candles DB: {candles_db_path}")

    # Load DBs
    conn_train = sqlite3.connect(training_db_path)
    conn_train.row_factory = sqlite3.Row
    conn_candles = sqlite3.connect(candles_db_path)

    # Initialize pattern memory DB
    pattern_db = PatternMemoryDB()

    # Query boxes that have outcome labels computed
    query = """
        SELECT * FROM review_queue
        WHERE outcome_computed_at IS NOT NULL
          AND outcome_future_return_20 IS NOT NULL
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    
    rows = conn_train.execute(query).fetchall()
    log.info(f"Found {len(rows)} boxes in review_queue with outcomes.")

    if not rows:
        log.info("No boxes to harvest.")
        conn_train.close()
        conn_candles.close()
        return

    # Load TimesFM predictor
    predictor = TimesFMPredictor(context_len=512, horizon_len=50)
    extractor = TimeFMEmbeddingExtractor(predictor)

    n_ok = 0
    n_fail = 0

    for i, row in enumerate(rows):
        row_dict = dict(row)
        box_id = row_dict["box_id"]
        
        # Check if already embedded
        if not overwrite:
            existing = pattern_db.get_pattern_by_id(box_id)
            # If pattern_id uses box_id, we can look up by box_id or pattern_id
            # Let's count by box_id in pattern_memory DB
            with pattern_db._conn() as conn_pm:
                count = conn_pm.execute("SELECT COUNT(*) FROM patterns WHERE box_id = ?", (box_id,)).fetchone()[0]
            if count > 0:
                log.debug(f"[{i+1}/{len(rows)}] Box {box_id} already harvested (skipped)")
                continue

        symbol = row_dict["symbol"]
        timeframe = row_dict["timeframe"]
        time_start = row_dict["time_start"]
        time_end = row_dict["time_end"]
        
        # Fetch candles
        candles = fetch_context_candles(conn_candles, symbol, timeframe, time_start, time_end, pre_candles=50)
        
        if not candles or len(candles) < 10:
            log.warning(f"[{i+1}/{len(rows)}] Box {box_id} failed to load context candles (n={len(candles)})")
            n_fail += 1
            continue

        # Find box indices inside fetched window
        # Candles ts is in seconds, box time is in milliseconds
        closes = [c["close"] for c in candles]
        ts_list = [c["time"] * 1000 for c in candles]
        
        # Find start and end indices
        start_idx = np.argmin([abs(t - time_start) for t in ts_list])
        end_idx = np.argmin([abs(t - time_end) for t in ts_list])

        # Extract embedding
        emb = extractor.get_embedding(candles, start_idx, end_idx, context_pre_candles=50)
        if emb is None:
            log.error(f"[{i+1}/{len(rows)}] Failed to extract embedding for box {box_id}")
            n_fail += 1
            continue

        # Build PatternRecord
        record = PatternRecord(
            box_id=box_id,
            symbol=symbol,
            exchange=row_dict.get("exchange") or "OANDA",
            timeframe=timeframe,
            box_time_start=time_start,
            box_time_end=time_end,
            price_high=row_dict["price_high"],
            price_low=row_dict["price_low"],
            box_width_candles=int(end_idx - start_idx + 1),
            quality_score=row_dict.get("score") or 0.0,
            is_valid=1 if row_dict["status"] in ("LABELED", "ANALYZED") else 0,
            embedding=emb,
            context_pre_candles=50,
            window_total_candles=len(candles),
            breakout_direction=row_dict["outcome_breakout_direction"],
            breakout_strength=row_dict["outcome_breakout_strength"],
            breakout_confirmed=row_dict["outcome_breakout_confirmed"],
            future_return_10=row_dict["outcome_future_return_10"],
            future_return_20=row_dict["outcome_future_return_20"],
            future_return_50=row_dict["outcome_future_return_50"],
            future_return_100=row_dict["outcome_future_return_100"],
            mfe=row_dict["outcome_mfe"],
            mae=row_dict["outcome_mae"],
            time_to_breakout=row_dict["outcome_time_to_breakout"],
            post_breakout_follow=row_dict["outcome_post_breakout_follow"],
            atr_at_box_end=row_dict["outcome_atr_at_box_end"],
            box_height_atr=row_dict["outcome_box_height_atr"],
            source="backfill" if row_dict["status"] in ("LABELED", "ANALYZED") else "auto_labeled",
            human_reviewed=1 if row_dict["status"] in ("LABELED", "ANALYZED") else 0
        )


        pattern_db.insert_pattern(record)
        n_ok += 1
        
        if n_ok % 50 == 0:
            log.info(f"Harvested {n_ok} patterns successfully...")

    log.info(f"Done. Successfully harvested: {n_ok} | Failed: {n_fail}")
    conn_train.close()
    conn_candles.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pattern Harvester CLI")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of boxes to harvest")
    parser.add_argument("--overwrite", action="store_true", help="Re-harvest and overwrite existing patterns")
    args = parser.parse_args()

    harvest(limit=args.limit, overwrite=args.overwrite)
