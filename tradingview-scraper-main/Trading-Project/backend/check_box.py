import sqlite3
from datetime import datetime, timezone, timedelta

def check_box():
    db_path = "training_set.db"
    box_id = "f4d2a99a50a98c83"
    ist = timezone(timedelta(hours=5, minutes=30))
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT box_id, time_start FROM review_queue WHERE box_id=?", (box_id,)).fetchone()
        
        if row:
            ts = row['time_start']
            dt_utc = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            dt_ist = dt_utc.astimezone(ist)
            
            print(f"Box ID: {box_id}")
            print(f"Timestamp (ms): {ts}")
            print(f"UTC: {dt_utc}")
            print(f"IST: {dt_ist}")
            print(f"IST Hour: {dt_ist.hour}")
            print(f"Is Midnight (0-5): {0 <= dt_ist.hour < 6}")
        else:
            print("Box not found.")

if __name__ == "__main__":
    check_box()
