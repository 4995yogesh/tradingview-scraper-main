import sqlite3
import json

db_path = "c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend/training_set.db"

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT ohlc_context FROM review_queue WHERE ohlc_context IS NOT NULL LIMIT 1").fetchone()
    if row:
        ctx = json.loads(row[0])
        print(f"Sample candle: {ctx[0]}")
    else:
        print("No samples found")
