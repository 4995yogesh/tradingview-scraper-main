import sqlite3
import json

try:
    conn = sqlite3.connect('training_set.db')
    c = conn.cursor()
    c.execute('SELECT box_id, status, gemini_analysis FROM review_queue WHERE status="ANALYZED" ORDER BY created_at DESC LIMIT 5')
    rows = c.fetchall()
    for r in rows:
        print(f"--- BOX: {r[0]} ---")
        print(f"STATUS: {r[1]}")
        print(f"CONTENT: {r[2][:500]}...")
except Exception as e:
    print(f"ERROR: {e}")
