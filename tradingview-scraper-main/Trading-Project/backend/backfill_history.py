"""
Historical Backfill Script
Reads all historical candles from candles.db, runs consolidation detection across all timeframes
(1m, 5m, 15m, 1h, 4h), and injects valid boxes into the active learning queue.
"""

import sys
import os
import sqlite3
import pandas as pd
import json
import hashlib
from datetime import datetime, timezone

# Add the project directory to sys.path so we can import consolidation
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "project"))
from indicators.consolidation import consolidation_boxes

# Use the exact same ID generation logic as server.py
def _compute_box_id_long(symbol: str, zone: dict) -> str:
    key = (
        f"{symbol}:{zone['timeframe']}:"
        f"{zone.get('timeStart', zone.get('time_start_ms'))}:"
        f"{zone.get('timeEnd', zone.get('time_end_ms'))}:"
        f"{float(zone.get('priceHigh', zone.get('price_high') or 0)):.5f}:"
        f"{float(zone.get('priceLow', zone.get('price_low') or 0)):.5f}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]

def main():
    SYMBOL = "EURUSD"
    TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
    CANDLE_DB = "../data/candles.db"
    TRAINING_DB = "training_set.db"

    # Connect to databases
    try:
        candle_conn = sqlite3.connect(CANDLE_DB)
    except Exception as e:
        print(f"Failed to connect to {CANDLE_DB}: {e}")
        return

    from training_db import TrainingDB
    train_db = TrainingDB(TRAINING_DB)

    total_added = 0

    for tf in TIMEFRAMES:
        print(f"Processing {tf}...")
        # Load all historical candles
        query = "SELECT ts as time, open, high, low, close, volume FROM candles WHERE symbol=? AND timeframe=? ORDER BY ts ASC"
        try:
            df = pd.read_sql_query(query, candle_conn, params=(SYMBOL, tf))
        except Exception as e:
            print(f"Error querying {tf}: {e}")
            continue

        if df.empty:
            print(f"  No candles found for {tf}")
            continue

        # Convert to expected format
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df.set_index('time', inplace=True)
        df.sort_index(inplace=True)
        
        # Format index as strings for JSON persistence
        df_json = df.copy()
        df_json['time'] = df_json.index.strftime('%Y-%m-%dT%H:%M:%SZ')

        print(f"  Loaded {len(df)} candles.")

        try:
            # Run detection (same as live)
            boxes_df = consolidation_boxes(df, min_bars=6, use_time_filter=(tf in ["1m", "5m", "15m", "1h"]))
            if boxes_df.empty:
                print(f"  No consolidations found.")
                continue
            
            added = 0
            df_len = len(df)
            
            for _, row in boxes_df.iterrows():
                si = int(row["start"])
                ei = int(row["end"])

                # Exact same guard as live: 5 candles after box
                if (ei + 5) <= (df_len - 1):
                    ts_start = int(pd.Timestamp(df.index[si]).timestamp() * 1000)
                    ts_end   = int(pd.Timestamp(df.index[ei]).timestamp() * 1000)
                    
                    zone_data = {
                        "symbol":    SYMBOL,
                        "timeframe": tf,
                        "timeStart": ts_start,
                        "timeEnd":   ts_end,
                        "priceHigh": float(row["top"]),
                        "priceLow":  float(row["bottom"]),
                        "type":      row.get("type", "LOOSE"),
                        "score":     float(row.get("score", 0.0))
                    }
                    
                    zone_data["box_id"] = _compute_box_id_long(SYMBOL, zone_data)
                    
                    # Context slice
                    ctx_s = max(0, si - 25)
                    ctx_e = min(df_len - 1, ei + 25)
                    ctx_df = df_json.iloc[ctx_s:ctx_e+1]
                    
                    train_db.upsert_box(zone_data, ctx_df.to_dict('records'))
                    added += 1

            print(f"  Added {added} boxes.")
            total_added += added

        except Exception as e:
            print(f"  Error processing {tf}: {e}")

    print(f"Backfill complete! Added {total_added} total boxes.")

if __name__ == "__main__":
    main()
