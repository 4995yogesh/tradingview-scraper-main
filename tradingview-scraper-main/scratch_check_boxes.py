import sqlite3
import json

c = sqlite3.connect('Trading-Project/backend/training_set.db')
boxes = c.execute('SELECT box_id, ohlc_context FROM review_queue').fetchall()
bad = []

for b, ctx in boxes:
    data = json.loads(ctx)
    doj_count = sum(1 for d in data if d['open'] == d['high'] == d['low'] == d['close'])
    gaps = sum(1 for i in range(1, len(data)) if abs(data[i]['open'] - data[i-1]['close']) > 0.00010)
    
    if doj_count > 3 or gaps > 0:
        bad.append(b)

print(f'Found {len(bad)} bad boxes out of {len(boxes)}')

for b in bad:
    c.execute('UPDATE review_queue SET interpretation = ? WHERE box_id = ?', ('INVALID_DATA', b))

c.commit()
print('Marked bad boxes as INVALID_DATA')
