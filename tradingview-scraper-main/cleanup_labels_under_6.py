import sqlite3
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.path.join(os.getcwd(), "Trading-Project"))
sys.path.append(os.path.join(os.getcwd(), "Trading-Project", "backend"))

from pipeline.data.db import candle_db

# Paths
ROOT = Path(os.getcwd()) / "Trading-Project"
LABEL_DB = ROOT / "backend" / "data" / "ml_feedback.db"

def cleanup():
    if not LABEL_DB.exists():
        print(f"Label DB not found at {LABEL_DB}")
        return

    conn = sqlite3.connect(str(LABEL_DB))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Fetch all labels
    cursor.execute("SELECT * FROM labels")
    labels = cursor.fetchall()
    
    total = len(labels)
    removed = 0
    print(f"Total labels to check: {total}")

    for row in labels:
        l = dict(row)
        box_id = l['box_id']
        symbol = l['symbol']
        tf = l['timeframe']
        t_start = l['time_start_ms'] // 1000
        t_end = l['time_end_ms'] // 1000
        price_h = l['price_high']
        price_l = l['price_low']
        exchange = l.get('exchange', 'OANDA')

        # Fetch candles
        candles = candle_db.get_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=tf,
            start_ts=t_start,
            end_ts=t_end
        )

        if not candles:
            # Maybe the data was purged? If no candles, we can't verify.
            # But the user wants to keep only boxes with >= 6.
            # If no data, we can't prove >= 6. We'll skip for now or remove?
            # Usually better to remove if we can't prove quality.
            print(f"No candles for box {box_id}, removing as unverifiable...")
            cursor.execute("DELETE FROM labels WHERE box_id = ?", (box_id,))
            cursor.execute("DELETE FROM features WHERE box_id = ?", (box_id,))
            removed += 1
            continue

        # Count closes inside
        closes_inside = 0
        for c in candles:
            if price_l <= float(c['close']) <= price_h:
                closes_inside += 1
        
        if closes_inside < 6:
            # DELETE
            print(f"Removing label {box_id} ({tf}): only {closes_inside} closes inside.")
            cursor.execute("DELETE FROM labels WHERE box_id = ?", (box_id,))
            cursor.execute("DELETE FROM features WHERE box_id = ?", (box_id,))
            removed += 1

    conn.commit()
    conn.close()
    print(f"\nCleanup complete. Removed {removed} labels out of {total}.")

if __name__ == "__main__":
    cleanup()
