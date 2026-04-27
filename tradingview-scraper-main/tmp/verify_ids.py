import sqlite3
import hashlib
import os

db_path = r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\data\ml_feedback.db'

def compute_box_id(symbol, timeframe, time_start):
    key = f"{symbol}:{timeframe}:{time_start}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]

def query_ids():
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- SAMPLE LABELS ---")
    cursor.execute("SELECT box_id, symbol, timeframe, time_start_ms, label FROM labels LIMIT 5")
    for row in cursor.fetchall():
        d = dict(row)
        expected = compute_box_id(d['symbol'], d['timeframe'], d['time_start_ms'])
        print(f"Stored: {d['box_id']} | Recalc: {expected} | Match: {d['box_id'] == expected}")
        print(d)
        
    conn.close()

if __name__ == "__main__":
    query_ids()
