import sqlite3
import os

db_path = r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend\data\ml_feedback.db'

def query_db():
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- MODELS ---")
    cursor.execute("SELECT version, precision_good, recall_good, promoted, trained_at FROM model_checkpoints ORDER BY trained_at DESC LIMIT 5")
    for row in cursor.fetchall():
        print(dict(row))
        
    print("\n--- LABEL DISTRIBUTION (LATEST PER BOX) ---")
    cursor.execute("""
        SELECT label, COUNT(*) as c FROM (
            SELECT box_id, label
            FROM labels l1
            WHERE created_at = (
                SELECT MAX(created_at) FROM labels l2 WHERE l2.box_id = l1.box_id
            )
            GROUP BY box_id
        ) GROUP BY label
    """)
    for row in cursor.fetchall():
        print(dict(row))
        
    conn.close()

if __name__ == "__main__":
    query_db()
