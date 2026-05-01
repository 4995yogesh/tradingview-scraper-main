import sqlite3
try:
    conn = sqlite3.connect('training_set.db')
    total_err = conn.execute("SELECT COUNT(*) FROM review_queue WHERE gemini_analysis LIKE '%Error%'").fetchone()[0]
    total_clean = conn.execute("SELECT COUNT(*) FROM review_queue WHERE status='ANALYZED' AND gemini_analysis NOT LIKE '%Error%'").fetchone()[0]
    print(f"STILL HAVE ERRORS: {total_err}")
    print(f"SUCCESSFULLY ANALYZED: {total_clean}")
    
    print("\n--- RECENT CLEAN SAMPLES ---")
    rows = conn.execute("SELECT box_id, gemini_analysis FROM review_queue WHERE status='ANALYZED' AND gemini_analysis NOT LIKE '%Error%' ORDER BY created_at DESC LIMIT 2").fetchall()
    for r in rows:
        print(f"ID: {r[0]} | CONTENT: {r[1][:100]}...")
except Exception as e:
    print(f"ERROR: {e}")
