import sqlite3
import os

project_root = "c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project"
candle_db_path = os.path.join(project_root, "data", "candles.db")

with sqlite3.connect(candle_db_path) as conn:
    res = conn.execute("SELECT DISTINCT exchange FROM candles").fetchall()
    print(f"Exchanges: {[r[0] for r in res]}")
