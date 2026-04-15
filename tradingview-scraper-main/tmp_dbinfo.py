import sqlite3, os, sys

candidates = [
    "Trading-Project/data/candles.db",
    "Trading-Project/backend/candles.db",
    "data/candles.db",
]
db = None
for c in candidates:
    if os.path.exists(c):
        db = c
        break

if db is None:
    print("DB not found in standard locations")
    sys.exit(1)

conn = sqlite3.connect(db)
rows = conn.execute(
    'SELECT timeframe, COUNT(*) as bars,'
    ' datetime(MIN(ts),"unixepoch") as oldest,'
    ' datetime(MAX(ts),"unixepoch") as newest'
    ' FROM candles GROUP BY timeframe ORDER BY timeframe'
).fetchall()
conn.close()

print(f"DB: {db}  ({os.path.getsize(db)/1024/1024:.1f} MB)")
print(f"{'TF':<6} {'BARS':>8}  {'OLDEST':<22} {'NEWEST':<22}")
print("-" * 65)
for tf, bars, old, new in rows:
    print(f"{tf:<6} {bars:>8}  {old:<22} {new:<22}")
