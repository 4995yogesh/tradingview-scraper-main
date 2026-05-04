import sqlite3
from datetime import datetime, timezone, timedelta

def list_hours():
    db_path = "training_set.db"
    ist = timezone(timedelta(hours=5, minutes=30))
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT box_id, time_start FROM review_queue").fetchall()
        
        hours = {}
        for r in rows:
            ts = r['time_start']
            dt_ist = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(ist)
            h = dt_ist.hour
            hours[h] = hours.get(h, 0) + 1
            
        print("IST Hour Distribution:")
        for h in sorted(hours.keys()):
            print(f"Hour {h:02d}: {hours[h]} boxes")

if __name__ == "__main__":
    list_hours()
