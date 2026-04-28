import sqlite3
import os
from pathlib import Path

DB_PATH = Path(r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\data\ml_quality.db")

def check_auto_labels():
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}")
        return
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM auto_labels LIMIT 10;")
    rows = cursor.fetchall()
    for r in rows:
        print(dict(r))
    
    cursor.execute("SELECT COUNT(*) FROM auto_labels;")
    print(f"Total rows: {cursor.fetchone()[0]}")
    conn.close()

if __name__ == "__main__":
    check_auto_labels()
