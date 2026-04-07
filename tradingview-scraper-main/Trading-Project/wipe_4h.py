import sqlite3
from pathlib import Path
import os
import sys

db_path = Path("c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/data/candles.db")
if not db_path.exists():
    print(f"DB not found at {db_path}")
    sys.exit(1)

conn = sqlite3.connect(str(db_path), timeout=20.0)
try:
    count_before = conn.execute("SELECT COUNT(*) FROM candles WHERE timeframe='4h'").fetchone()[0]
    print(f"4h candles before wipe: {count_before}")
    
    conn.execute("DELETE FROM candles WHERE timeframe='4h'")
    conn.commit()
    
    count_after = conn.execute("SELECT COUNT(*) FROM candles WHERE timeframe='4h'").fetchone()[0]
    print(f"4h candles after wipe: {count_after}")
    
    print("Successfully deleted polluted 4h candles.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
