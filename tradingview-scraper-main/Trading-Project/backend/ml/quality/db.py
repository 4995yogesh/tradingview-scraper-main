import sqlite3
import os
import time
import json
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ml_quality.db")

@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        # Table for quality features & metadata (separate from existing)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_store (
                box_id TEXT PRIMARY KEY,
                features TEXT,
                label_score REAL,
                prediction REAL,
                created_at INTEGER
            )
        """)
        # For tracking experiments
        conn.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                rmse REAL,
                feature_importance TEXT,
                trained_at INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_labels (
                box_id TEXT PRIMARY KEY,
                label TEXT,
                confidence REAL,
                status TEXT,
                approved INTEGER,
                start INTEGER,
                end INTEGER,
                reason TEXT,
                timestamp INTEGER
            )
        """)

def save_auto_label(box_id, label, confidence, status, approved, reason, start=None, end=None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO auto_labels (box_id, label, confidence, status, approved, reason, start, end, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(box_id) DO UPDATE SET
                label = excluded.label,
                confidence = excluded.confidence,
                status = excluded.status,
                approved = excluded.approved,
                reason = excluded.reason,
                start = excluded.start,
                end = excluded.end,
                timestamp = excluded.timestamp
        """, (box_id, label, confidence, status, 1 if approved else 0, reason, start, end, int(time.time())))

def get_auto_labels():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM auto_labels").fetchall()
        return {r['box_id']: dict(r) for r in rows}

def save_quality_sample(box_id, features, label_score):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO quality_store (box_id, features, label_score, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(box_id) DO UPDATE SET
                features = excluded.features,
                label_score = excluded.label_score
        """, (box_id, json.dumps(features), label_score, int(time.time())))

def get_all_samples():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM quality_store ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]

# Auto-initialize database tables on module load
try:
    init_db()
except Exception as _e:
    logger.error("Failed to auto-initialize ml_quality.db: %s", _e)

