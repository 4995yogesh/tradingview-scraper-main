import sqlite3
import json
import os

backend_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(backend_dir, "training_set.db")

with sqlite3.connect(db_path) as conn:
    row = conn.execute("SELECT box_id, ohlc_context FROM review_queue LIMIT 1").fetchone()
    if row:
        ctx = json.loads(row[1])
        print(f"Box {row[0]} has {len(ctx)} context candles.")
        if len(ctx) > 0:
            print(f"Sample candle time: {ctx[0]['time']}")
    else:
        print("No boxes in queue.")
