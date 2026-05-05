import sqlite3, json

conn = sqlite3.connect('Trading-Project/backend/training_set.db')
cur = conn.cursor()

cur.execute("""
SELECT COUNT(*) FROM review_queue 
WHERE status = 'PENDING_SCREENSHOT' 
AND ohlc_context IS NOT NULL AND ohlc_context != ''
AND original_meta IS NOT NULL AND original_meta != ''
""")
print('valid PENDING_SCREENSHOT:', cur.fetchone()[0])

cur.execute("""
SELECT original_meta FROM review_queue 
WHERE status = 'PENDING_SCREENSHOT' 
AND original_meta IS NOT NULL LIMIT 1
""")
row = cur.fetchone()
if row:
    m = json.loads(row[0])
    print('original_meta keys:', list(m.keys()))

conn.close()
