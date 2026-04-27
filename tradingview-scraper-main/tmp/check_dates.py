import sqlite3
db = r'Trading-Project\backend\data\ml_feedback.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
r1 = conn.execute('SELECT created_at FROM labels WHERE timeframe="15m" LIMIT 1').fetchone()
r2 = conn.execute('SELECT created_at FROM labels WHERE timeframe="1m" LIMIT 1').fetchone()
print("15m created:", r1["created_at"] if r1 else None)
print("1m created:", r2["created_at"] if r2 else None)
