import sqlite3
conn = sqlite3.connect('training_set.db')
cursor = conn.execute("SELECT * FROM training_status ORDER BY id DESC LIMIT 1")
row = cursor.fetchone()
print(row)
conn.close()
