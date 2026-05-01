import sqlite3
import json
import os
from datetime import datetime

class TrainingDB:
    def __init__(self, db_path="training_set.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_queue (
                    box_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    timeframe TEXT,
                    time_start INTEGER,
                    time_end INTEGER,
                    price_high REAL,
                    price_low REAL,
                    ohlc_context TEXT, -- JSON string of surrounding candles
                    original_meta TEXT, -- original scores/type
                    user_box TEXT, -- JSON of user-drawn ideal box
                    gemini_analysis TEXT,
                    screenshot_b64 TEXT, -- The captured canvas image
                    status TEXT DEFAULT 'PENDING_SCREENSHOT', -- PENDING_SCREENSHOT, PENDING, LABELED, ANALYZED
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS training_status (
                    id INTEGER PRIMARY KEY,
                    status TEXT,
                    epoch INTEGER,
                    loss REAL,
                    val_loss REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def upsert_box(self, box_data, ohlc_context):
        """
        Adds or updates a box in the review queue.
        box_data: dict from consolidation detector
        ohlc_context: list of candles around the box
        """
        box_id = box_data.get('box_id')
        if not box_id:
            return

        with sqlite3.connect(self.db_path) as conn:
            # Check if exists to avoid overwriting LABELED boxes
            cursor = conn.execute("SELECT status FROM review_queue WHERE box_id = ?", (box_id,))
            row = cursor.fetchone()
            if row and row[0] != 'PENDING':
                return

            conn.execute("""
                INSERT INTO review_queue (
                    box_id, symbol, timeframe, time_start, time_end, 
                    price_high, price_low, ohlc_context, original_meta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(box_id) DO UPDATE SET
                    time_end = excluded.time_end,
                    price_high = excluded.price_high,
                    price_low = excluded.price_low,
                    ohlc_context = excluded.ohlc_context
            """, (
                box_id,
                box_data.get('symbol'),
                box_data.get('timeframe'),
                box_data.get('timeStart'),
                box_data.get('timeEnd'),
                box_data.get('priceHigh'),
                box_data.get('priceLow'),
                json.dumps(ohlc_context),
                json.dumps(box_data)
            ))
            conn.commit()

    def get_needs_screenshot(self, symbol, timeframe):
        """Returns boxes for this symbol/TF that don't have a screenshot yet."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT box_id, time_start, time_end, ohlc_context FROM review_queue WHERE symbol=? AND timeframe=? AND status='PENDING_SCREENSHOT'",
                (symbol, timeframe)
            )
            rows = [dict(row) for row in cursor.fetchall()]
            valid_rows = []
            for r in rows:
                try:
                    ctx = json.loads(r["ohlc_context"])
                    doj_count = sum(1 for d in ctx if d['open'] == d['high'] == d['low'] == d['close'])
                    max_gap = max([0] + [abs(ctx[i]['open'] - ctx[i-1]['close']) for i in range(1, len(ctx))])
                    if doj_count > 3 or max_gap > 0.00200:
                        # Auto-fail the corrupt box so it doesn't get stuck in PENDING_SCREENSHOT forever
                        conn.execute("UPDATE review_queue SET status='INVALID_DATA' WHERE box_id=?", (r["box_id"],))
                        continue
                    valid_rows.append({"box_id": r["box_id"], "time_start": r["time_start"], "time_end": r["time_end"]})
                except Exception:
                    valid_rows.append({"box_id": r["box_id"], "time_start": r["time_start"], "time_end": r["time_end"]})
            conn.commit()
            return valid_rows

    def save_screenshot(self, box_id, b64_data):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE review_queue SET screenshot_b64 = ?, status = 'PENDING' WHERE box_id = ?",
                (b64_data, box_id)
            )
            conn.commit()

    def get_pending(self, limit=50):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM review_queue WHERE status = 'PENDING' ORDER BY created_at DESC"
            )
            rows = [dict(row) for row in cursor.fetchall()]
            
            valid_rows = []
            for r in rows:
                if len(valid_rows) >= limit:
                    break
                try:
                    ctx = json.loads(r["ohlc_context"])
                    doj_count = sum(1 for d in ctx if d['open'] == d['high'] == d['low'] == d['close'])
                    max_gap = max([0] + [abs(ctx[i]['open'] - ctx[i-1]['close']) for i in range(1, len(ctx))])
                    if doj_count > 3 or max_gap > 0.00200:
                        conn.execute("UPDATE review_queue SET status='INVALID_DATA' WHERE box_id=?", (r["box_id"],))
                        continue
                    valid_rows.append(r)
                except Exception:
                    valid_rows.append(r)
            conn.commit()
            return valid_rows

    def update_label(self, box_id, user_box):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE review_queue SET user_box = ?, status = 'LABELED' WHERE box_id = ?",
                (json.dumps(user_box), box_id)
            )
            conn.commit()
            cursor = conn.execute("SELECT COUNT(*) FROM review_queue WHERE status = 'LABELED'")
            return cursor.fetchone()[0]

    def update_training_progress(self, status, epoch=0, loss=0, val_loss=0):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO training_status (id, status, epoch, loss, val_loss, updated_at)
                VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    epoch = excluded.epoch,
                    loss = excluded.loss,
                    val_loss = excluded.val_loss,
                    updated_at = excluded.updated_at
            """, (status, epoch, loss, val_loss))
            conn.commit()

    def get_training_status(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM training_status WHERE id = 1")
            row = cursor.fetchone()
            return dict(row) if row else {"status": "IDLE"}

    def skip_box(self, box_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE review_queue SET status = 'SKIPPED' WHERE box_id = ?",
                (box_id,)
            )
            conn.commit()

    def reset_box(self, box_id):
        with sqlite3.connect(self.db_path) as conn:
            # Revert to PENDING (or PENDING_SCREENSHOT if it was originally that)
            # For simplicity, we restore to PENDING as Studio only handles PENDING+
            conn.execute(
                "UPDATE review_queue SET user_box = NULL, gemini_analysis = NULL, status = 'PENDING' WHERE box_id = ?",
                (box_id,)
            )
            conn.commit()

training_db = TrainingDB()
