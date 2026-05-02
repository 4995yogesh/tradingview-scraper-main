import sqlite3, json
conn = sqlite3.connect('training_set.db')
c = conn.cursor()
c.execute("SELECT box_id, user_box FROM review_queue WHERE status IN ('LABELED','ANALYZED') AND user_box IS NOT NULL")
for bid, ub_str in c.fetchall():
    ub = json.loads(ub_str)
    ub_dict = ub[0] if isinstance(ub, list) else ub
    if 'timeStart' not in ub_dict:
        print(f"box_id {bid} missing timeStart: {list(ub_dict.keys())}")
conn.close()
