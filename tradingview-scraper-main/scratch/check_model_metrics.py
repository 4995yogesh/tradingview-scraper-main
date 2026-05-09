import sqlite3
import os
import json

db_path = r"Trading-Project/data/ml_feedback.db"
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM model_checkpoints WHERE promoted=1 ORDER BY trained_at DESC LIMIT 1").fetchone()
conn.close()

if row:
    print(json.dumps(dict(row), indent=4))
else:
    print("No promoted model found.")
