import sqlite3
import os
from pathlib import Path

ROOT = Path(os.getcwd()) / "Trading-Project"
LABEL_DB = ROOT / "data" / "ml_feedback.db"

def list_tables():
    if not LABEL_DB.exists():
        print(f"Label DB not found at {LABEL_DB}")
        return
    conn = sqlite3.connect(str(LABEL_DB))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print(cursor.fetchall())
    conn.close()

if __name__ == "__main__":
    list_tables()
