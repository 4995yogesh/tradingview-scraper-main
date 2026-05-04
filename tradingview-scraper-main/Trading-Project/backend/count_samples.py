import sqlite3
import os

db_path = r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\training_set.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM review_queue WHERE status IN ('LABELED','ANALYZED')").fetchone()[0]
    print(f"Total labeled samples: {count}")
    conn.close()
else:
    print("DB not found")
