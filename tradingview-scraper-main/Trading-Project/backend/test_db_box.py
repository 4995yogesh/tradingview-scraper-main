import sqlite3
import json

try:
    conn = sqlite3.connect('c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend/training_set.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM review_queue')
    print("TOTAL:", c.fetchone()[0])
    
    c.execute('SELECT box_id, status FROM review_queue WHERE box_id="d456f61b80cc566f"')
    row = c.fetchone()
    if row:
        print("FOUND BOX:", row[0], "STATUS:", row[1])
    else:
        print("BOX NOT FOUND IN DB!")
        
    c.execute('SELECT box_id, status FROM review_queue LIMIT 5')
    print("Sample boxes:", c.fetchall())
except Exception as e:
    print(e)
