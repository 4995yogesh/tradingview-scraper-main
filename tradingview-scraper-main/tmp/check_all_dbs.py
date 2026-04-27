import sqlite3
import os

paths = [
    r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\dist\TradingDashboard\Trading-Project\backend\data\ml_feedback.db',
    r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\data\ml_feedback.db',
    r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\data\ml_feedback.db'
]

for p in paths:
    if os.path.exists(p):
        conn = sqlite3.connect(p)
        c = conn.execute("SELECT COUNT(*) FROM labels")
        count = c.fetchone()[0]
        print(f"Path: {p} | Labels: {count}")
        conn.close()
    else:
        print(f"Path: {p} | NOT FOUND")
