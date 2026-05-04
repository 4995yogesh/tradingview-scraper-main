import sqlite3
import os
import sys
import pandas as pd
import json
import time
from datetime import datetime, timezone, timedelta
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project'))

from indicators.consolidation import consolidation_boxes
from training_db import training_db

# Mock logger for server logic reuse
class MockLogger:
    def debug(self, msg, *args): pass
    def info(self, msg, *args): print(msg % args)
    def warning(self, msg, *args): print(msg % args)
    def error(self, msg, *args): print(msg % args)

logger = MockLogger()

def compute_box_id_long(symbol, z):
    import hashlib
    # Unique ID based on symbol, timeframe, start time and price range
    # Ensure times are integers
    s = f"{symbol}_{z['timeframe']}_{z['timeStart']}_{z['timeEnd']}_{z['priceHigh']:.6f}_{z['priceLow']:.6f}"
    return hashlib.md_hash(s.encode()).hexdigest() if hasattr(hashlib, 'md_hash') else hashlib.md5(s.encode()).hexdigest()

def restore():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'candles.db')
    ist = timezone(timedelta(hours=5, minutes=30))
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Get all symbols and timeframes
        series = conn.execute("SELECT DISTINCT exchange, symbol, timeframe FROM candles").fetchall()
        
        for s in series:
            ex, sym, tf = s['exchange'], s['symbol'], s['timeframe']
            if tf not in ["5m", "15m", "1h"]: continue
            
            print(f"Processing {sym} [{tf}]...")
            rows = conn.execute(
                "SELECT ts as timestamp, open, high, low, close, volume FROM candles WHERE exchange=? AND symbol=? AND timeframe=? ORDER BY ts ASC",
                (ex, sym, tf)
            ).fetchall()
            
            if not rows: continue
            
            df = pd.DataFrame([dict(r) for r in rows])
            df.index = pd.to_datetime(df["timestamp"], unit='s', utc=True)
            
            apply_time_filter = tf in ["1m", "5m", "15m", "1h"]
            boxes_df = consolidation_boxes(df, min_bars=6, use_time_filter=apply_time_filter)
            
            if boxes_df.empty: continue
            
            df_len = len(df)
            idx = df.index
            restored_count = 0
            
            for _, row in boxes_df.iterrows():
                try:
                    si = int(row["start"])
                    ei = int(row["end"])
                    if si >= df_len or ei >= df_len: continue
                    
                    ts_start = int(pd.Timestamp(idx[si]).timestamp() * 1000)
                    ts_end   = int(pd.Timestamp(idx[ei]).timestamp() * 1000)
                    
                    # Apply CURRENT Midnight Filter (00:00 - 05:59 IST)
                    dt_ist = datetime.fromtimestamp(ts_start / 1000, tz=timezone.utc).astimezone(ist)
                    if 0 <= dt_ist.hour < 6:
                        continue
                        
                    zone_data = {
                        "symbol":    sym,
                        "timeframe": tf,
                        "timeStart": ts_start,
                        "timeEnd":   ts_end,
                        "priceHigh": float(row["top"]),
                        "priceLow":  float(row["bottom"]),
                        "type":      row.get("type", "LOOSE"),
                        "score":     float(row.get("score", 0.0))
                    }
                    zid = compute_box_id_long(sym, zone_data)
                    zone_data["box_id"] = zid
                    
                    # Context (25+25 as per latest logic)
                    ctx_s = max(0, si - 25)
                    ctx_e = min(df_len - 1, ei + 25)
                    ctx_df = df.iloc[ctx_s:ctx_e+1].copy()
                    ctx_df['time'] = ctx_df.index.strftime('%Y-%m-%dT%H:%M:%SZ')
                    
                    # This will insert if missing
                    training_db.upsert_box(zone_data, ctx_df.to_dict('records'))
                    restored_count += 1
                except Exception as e:
                    pass
            
            if restored_count > 0:
                print(f"Restored {restored_count} boxes for {sym} [{tf}]")

if __name__ == "__main__":
    restore()
