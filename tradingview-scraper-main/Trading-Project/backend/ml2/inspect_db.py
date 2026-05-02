import sys, os, json, sqlite3
sys.path.insert(0, 'ml2')

conn = sqlite3.connect('training_set.db')
c = conn.cursor()
c.execute("SELECT box_id, user_box FROM review_queue WHERE status IN ('LABELED','ANALYZED') AND user_box IS NOT NULL LIMIT 3")
rows = c.fetchall()
conn.close()

for bid, ub_str in rows:
    ub = json.loads(ub_str)
    print(f"box_id: {bid}")
    print(f"user_box type: {type(ub)}")
    if isinstance(ub, list):
        print(f"  list len: {len(ub)}")
        if ub: print(f"  first item keys: {list(ub[0].keys())}")
    elif isinstance(ub, dict):
        print(f"  dict keys: {list(ub.keys())}")
    print()
