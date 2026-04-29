"""
Cleanup: delete all review_queue rows where fewer than 5 valid candles exist
after the box's time_end in the stored ohlc_context.
Valid = not a ghost candle (open==high==low==close) and not a weekend (Sat/Sun UTC).
"""
import sqlite3
import json
from datetime import datetime, timezone

DB = "training_set.db"
MIN_RIGHT_CANDLES = 5


def is_weekend(time_str):
    try:
        d = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return d.weekday() >= 5  # 5=Sat, 6=Sun
    except Exception:
        return False


def is_ghost(c):
    return c['open'] == c['high'] == c['low'] == c['close']


def count_right_candles(ohlc_list, time_end_ms):
    """Count valid candles that come AFTER time_end_ms in the ohlc context."""
    count = 0
    for c in ohlc_list:
        try:
            t = datetime.strptime(c['time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            t_ms = int(t.timestamp() * 1000)
        except Exception:
            continue
        if t_ms <= time_end_ms:
            continue
        if is_ghost(c) or is_weekend(c['time']):
            continue
        count += 1
    return count


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT box_id, time_end, ohlc_context FROM review_queue WHERE status NOT IN ('LABELED', 'ANALYZED')"
).fetchall()

delete_ids = []
for row in rows:
    try:
        ohlc = json.loads(row['ohlc_context'])
        right = count_right_candles(ohlc, row['time_end'])
        if right < MIN_RIGHT_CANDLES:
            delete_ids.append(row['box_id'])
    except Exception as e:
        print(f"Parse error for {row['box_id']}: {e}")
        delete_ids.append(row['box_id'])  # delete corrupt rows too

print(f"Total rows checked : {len(rows)}")
print(f"Rows to delete      : {len(delete_ids)}")
print(f"Rows to keep        : {len(rows) - len(delete_ids)}")

if delete_ids:
    placeholders = ','.join('?' * len(delete_ids))
    conn.execute(f"DELETE FROM review_queue WHERE box_id IN ({placeholders})", delete_ids)
    conn.commit()
    print("Deleted successfully.")

conn.close()
