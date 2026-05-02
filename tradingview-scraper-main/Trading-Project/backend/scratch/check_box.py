import sqlite3
import json
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(backend_dir, "training_set.db")

box_id = "7e137c632f833c49"

with sqlite3.connect(db_path) as conn:
    row = conn.execute("SELECT ohlc_context, time_start, time_end FROM review_queue WHERE box_id=?", (box_id,)).fetchone()
    if row:
        ctx = json.loads(row[0])
        print(f"Box {box_id} has {len(ctx)} context candles.")
        if len(ctx) > 0:
            print(f"Box start: {row[1]}, Box end: {row[2]}")
            print(f"First candle in context: {ctx[0]['time']}")
            print(f"Last candle in context: {ctx[-1]['time']}")
    else:
        print(f"Box {box_id} not found.")
