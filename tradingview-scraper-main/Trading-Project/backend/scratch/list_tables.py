import sqlite3
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(backend_dir, "training_set.db")

with sqlite3.connect(db_path) as conn:
    res = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"Tables: {[r[0] for r in res]}")
