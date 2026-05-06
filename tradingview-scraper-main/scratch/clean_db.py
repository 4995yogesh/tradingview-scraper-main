import sqlite3
conn = sqlite3.connect('Trading-Project/backend/training_set.db')
cursor = conn.cursor()
cursor.execute("DELETE FROM review_queue WHERE status IN ('PENDING', 'PENDING_SCREENSHOT')")
print('Deleted old boxes:', cursor.rowcount)
conn.commit()
