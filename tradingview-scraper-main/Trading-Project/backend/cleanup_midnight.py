import sqlite3
from datetime import datetime, timezone, timedelta

def cleanup_midnight_boxes():
    db_path = "training_set.db"
    ist = timezone(timedelta(hours=5, minutes=30))
    
    print(f"Connecting to {db_path}...")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT box_id, time_start FROM review_queue")
        rows = cursor.fetchall()
        
        to_delete = []
        for r in rows:
            ts = r['time_start']
            # ts is in ms
            dt_ist = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(ist)
            
            if 0 <= dt_ist.hour < 6:
                to_delete.append(r['box_id'])
        
        if to_delete:
            print(f"Found {len(to_delete)} midnight boxes. Deleting...")
            for i in range(0, len(to_delete), 100):
                chunk = to_delete[i:i+100]
                conn.execute(f"DELETE FROM review_queue WHERE box_id IN ({','.join(['?']*len(chunk))})", chunk)
            conn.commit()
            print("Cleanup complete.")
        else:
            print("No midnight boxes found.")

if __name__ == "__main__":
    cleanup_midnight_boxes()
