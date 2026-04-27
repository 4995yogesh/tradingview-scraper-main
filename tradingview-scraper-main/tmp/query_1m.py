import sqlite3
db = r'Trading-Project\backend\data\ml_feedback.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT box_id, symbol, timeframe, time_start_ms FROM labels WHERE timeframe='1m' LIMIT 5").fetchall()
for r in rows:
    print(dict(r))
