import sqlite3, os

# Check both possible DB paths
paths = [
    r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\training_set.db',
    r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Training-Project\training_set.db',
    r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\training_set.db',
]

for p in paths:
    if os.path.exists(p):
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM review_queue GROUP BY status")
        rows = cur.fetchall()
        conn.close()
        print(f"\n=== {p} ===")
        for r in rows:
            print(r)
    else:
        print(f"NOT FOUND: {p}")
