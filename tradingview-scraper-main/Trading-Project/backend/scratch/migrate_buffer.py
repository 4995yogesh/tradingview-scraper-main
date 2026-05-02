import sqlite3
import json
import os
import sys

# Add project paths
backend_dir = os.path.dirname(os.path.abspath(__file__)) # .../backend/scratch
project_root = os.path.dirname(os.path.dirname(backend_dir)) # .../Trading-Project
sys.path.append(project_root)

from pipeline.data.db import candle_db

db_path = os.path.join(os.path.dirname(backend_dir), "training_set.db")

def migrate_context():
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT box_id, symbol, timeframe, time_start, time_end FROM review_queue").fetchall()
        
        print(f"Migrating {len(rows)} boxes to 15+15 buffer...")
        
        for r in rows:
            symbol = r["symbol"]
            tf = r["timeframe"]
            ts_start = r["time_start"]
            ts_end = r["time_end"]
            
            # Fetch context candles from SQLite (ts_start - 30 candles context to be safe)
            # 1 candle in 1h = 3600s. 30 candles = 108000s.
            # We fetch a larger window and slice precisely in Python.
            
            # Convert ms to s for SQLite
            s_start = ts_start // 1000
            s_end   = ts_end // 1000
            
            # Fetch roughly 50 candles around the area
            buffer_s = 30 * 3600 # extreme case for 1h, for 1m it's too much but fine
            if tf == '1m': buffer_s = 50 * 60
            elif tf == '5m': buffer_s = 50 * 300
            elif tf == '15m': buffer_s = 50 * 900
            
            candles = candle_db.get_candles(
                "OANDA", symbol, tf, 
                start_ts=s_start - buffer_s, 
                end_ts=s_end + buffer_s
            )
            
            if not candles:
                continue
                
            # Find indices
            si = -1
            ei = -1
            # get_candles returns dicts with 'ts'
            for i, c in enumerate(candles):
                if c['ts'] * 1000 >= ts_start and si == -1:
                    si = i
                if c['ts'] * 1000 >= ts_end and ei == -1:
                    ei = i
                    break
            
            if si != -1 and ei != -1:
                # Slice 15 before and 15 after
                ctx_s = max(0, si - 15)
                ctx_e = min(len(candles) - 1, ei + 15)
                ctx_slice = candles[ctx_s:ctx_e+1]
                
                # Format to expected frontend format (time, open, high, low, close)
                formatted = []
                from datetime import datetime, timezone
                for c in ctx_slice:
                    formatted.append({
                        'time': datetime.fromtimestamp(c['ts'], tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'open': c['open'],
                        'high': c['high'],
                        'low': c['low'],
                        'close': c['close'],
                        'volume': c.get('volume', 0)
                    })
                
                conn.execute("UPDATE review_queue SET ohlc_context=? WHERE box_id=?", (json.dumps(formatted), r["box_id"]))
        
        conn.commit()
    print("Migration complete.")

if __name__ == "__main__":
    migrate_context()
