import sqlite3
import json
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(backend_dir, "training_set.db")

with sqlite3.connect(db_path) as conn:
    # Check 5 boxes
    rows = conn.execute("SELECT box_id, symbol, timeframe, ohlc_context FROM review_queue LIMIT 5").fetchall()
    for row in rows:
        ctx = json.loads(row[3])
        print(f"Box {row[0]} ({row[1]} {row[2]}) has {len(ctx)} context candles.")
