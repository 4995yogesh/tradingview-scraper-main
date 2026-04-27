import sqlite3
db = r'Trading-Project\backend\data\ml_feedback.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT * FROM labels WHERE box_id='e34d5eef08891b37'").fetchone()
print(dict(r) if r else "Not found")
