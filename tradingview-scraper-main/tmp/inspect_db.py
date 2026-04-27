import sqlite3
import os

db_path = r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\data\ml_feedback.db'

def inspect_db():
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("--- TABLES ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    for table in tables:
        print(table[0])
        cursor.execute(f"PRAGMA table_info({table[0]})")
        print(cursor.fetchall())
        
    conn.close()

if __name__ == "__main__":
    inspect_db()
