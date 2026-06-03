import sqlite3
from pathlib import Path

db_path = Path("c:/Users/ysssi/Desktop/Tradingview_Main/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/data/candles.db")

if not db_path.exists():
    print(f"Database not found at {db_path}")
    exit(1)

print(f"Connecting to database at {db_path}...")
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

# 1. Show all series stored in database
print("\n--- Series Summary ---")
rows = conn.execute("SELECT exchange, symbol, timeframe, COUNT(*), MIN(ts), MAX(ts), MIN(close), MAX(close) FROM candles GROUP BY exchange, symbol, timeframe").fetchall()
for r in rows:
    print(dict(r))

# 2. Show a few recent XAUUSD candles
print("\n--- Sample XAUUSD Candles ---")
rows = conn.execute("SELECT * FROM candles WHERE symbol='XAUUSD' ORDER BY ts DESC LIMIT 10").fetchall()
for r in rows:
    import datetime
    dt = datetime.datetime.fromtimestamp(r['ts'], datetime.timezone.utc)
    print(f"TS: {dt} ({r['ts']}), O: {r['open']}, H: {r['high']}, L: {r['low']}, C: {r['close']}, Vol: {r['volume']}")

conn.close()
