"""
ml/db.py — Label storage, feature store, model checkpoint DB layer.

Migration-safe: all CREATE TABLE IF NOT EXISTS.
No DROP / ALTER — existing data preserved.
"""

import sqlite3
import json
import os
import time
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# DB path — same folder as existing ml_feedback.db
_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ml_feedback.db")

@contextmanager
def _conn():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Migrations ────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Run all migrations at server startup. Idempotent."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

    # Ensure models directory exists
    models_dir = os.path.join(os.path.dirname(__file__), "..", "data", "models")
    os.makedirs(models_dir, exist_ok=True)

    with _conn() as conn:
        # Labels table — NO UNIQUE constraint on box_id (allow relabeling)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id             TEXT NOT NULL,
                exchange           TEXT NOT NULL DEFAULT 'OANDA',
                symbol             TEXT NOT NULL DEFAULT 'EURUSD',
                timeframe          TEXT NOT NULL,
                time_start_ms      INTEGER NOT NULL,
                time_end_ms        INTEGER NOT NULL,
                price_high         REAL NOT NULL,
                price_low          REAL NOT NULL,
                label              TEXT NOT NULL CHECK(label IN ('good','bad','neutral')),
                schema_ver         INTEGER NOT NULL DEFAULT 1,
                train_consumed     INTEGER NOT NULL DEFAULT 0,
                created_at         INTEGER NOT NULL,
                feature_ver        TEXT NOT NULL DEFAULT 'v1',
                model_version_used TEXT
            )
        """)
        # Index for latest-per-box lookup
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_labels_box_created
                ON labels(box_id, created_at DESC)
        """)

        # Model checkpoints
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_checkpoints (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                version        TEXT NOT NULL,
                trained_at     INTEGER NOT NULL,
                label_count    INTEGER NOT NULL,
                precision_good REAL,
                recall_good    REAL,
                f1_good        REAL,
                support_good   INTEGER,
                promoted       INTEGER NOT NULL DEFAULT 0,
                pkl_path       TEXT NOT NULL,
                feature_ver    TEXT NOT NULL DEFAULT 'v1'
            )
        """)

        # Feature store — JSON (not blob)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS features (
                box_id       TEXT PRIMARY KEY,
                feature_vec  TEXT NOT NULL,
                feature_ver  TEXT NOT NULL,
                created_at   INTEGER NOT NULL
            )
        """)

    logger.info("[ml.db] init_db() complete — tables ready")


# ── Label operations ──────────────────────────────────────────────────────────

def save_label(
    box_id: str,
    label: str,
    zone_meta: dict,
    feature_ver: str = "v1",
    model_version_used: Optional[str] = None,
) -> int:
    """Insert a label row. Returns new label id."""
    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO labels
                (box_id, exchange, symbol, timeframe,
                 time_start_ms, time_end_ms, price_high, price_low,
                 label, created_at, feature_ver, model_version_used)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            box_id,
            zone_meta.get("exchange", "OANDA"),
            zone_meta.get("symbol", "EURUSD"),
            zone_meta.get("timeframe", ""),
            zone_meta.get("timeStart", 0),
            zone_meta.get("timeEnd", 0),
            zone_meta.get("priceHigh", 0.0),
            zone_meta.get("priceLow", 0.0),
            label,
            int(time.time()),
            feature_ver,
            model_version_used,
        ))
        return cur.lastrowid


def get_latest_label(box_id: str) -> Optional[dict]:
    """Return the most recent label for a box, or None."""
    with _conn() as conn:
        row = conn.execute("""
            SELECT * FROM labels
            WHERE box_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (box_id,)).fetchone()
        return dict(row) if row else None


def get_labels_for_boxes(box_ids: list) -> dict:
    """Return {box_id: label_str | None} for a list of box_ids."""
    if not box_ids:
        return {}
    placeholders = ",".join("?" * len(box_ids))
    with _conn() as conn:
        rows = conn.execute(f"""
            SELECT box_id, label, created_at
            FROM labels
            WHERE box_id IN ({placeholders})
            ORDER BY created_at DESC
        """, box_ids).fetchall()

    # Keep latest per box
    result: dict = {}
    for row in rows:
        bid = row["box_id"]
        if bid not in result:
            result[bid] = row["label"]
    # Fill missing
    for bid in box_ids:
        if bid not in result:
            result[bid] = None
    return result


def count_unconsumed() -> int:
    """Count labels not yet used in training (train_consumed=0)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM labels WHERE train_consumed=0"
        ).fetchone()
        return row["n"] if row else 0


def count_all_labels() -> int:
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM labels").fetchone()
        return row["n"] if row else 0


def get_unconsumed_labels() -> list:
    """Return all unconsumed label rows (one per row, may have duplicates per box)."""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT * FROM labels
            WHERE train_consumed = 0
            ORDER BY created_at ASC
        """).fetchall()
        return [dict(r) for r in rows]


def mark_consumed(label_ids: list) -> None:
    """Mark label rows as consumed after successful training."""
    if not label_ids:
        return
    placeholders = ",".join("?" * len(label_ids))
    with _conn() as conn:
        conn.execute(
            f"UPDATE labels SET train_consumed=1 WHERE id IN ({placeholders})",
            label_ids,
        )


# ── Feature store ─────────────────────────────────────────────────────────────

def save_feature_vec(box_id: str, vec: list, ver: str = "v1") -> None:
    """Upsert feature vector as JSON string."""
    with _conn() as conn:
        conn.execute("""
            INSERT INTO features (box_id, feature_vec, feature_ver, created_at)
            VALUES (?,?,?,?)
            ON CONFLICT(box_id) DO UPDATE SET
                feature_vec = excluded.feature_vec,
                feature_ver = excluded.feature_ver,
                created_at  = excluded.created_at
        """, (box_id, json.dumps(vec), ver, int(time.time())))


def get_feature_vec(box_id: str) -> Optional[list]:
    """Return feature vector as Python list, or None if missing."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT feature_vec, feature_ver FROM features WHERE box_id=?",
            (box_id,)
        ).fetchone()
        if not row:
            return None
        return json.loads(row["feature_vec"])


def has_feature(box_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM features WHERE box_id=?", (box_id,)
        ).fetchone()
        return row is not None


# ── Model checkpoints ─────────────────────────────────────────────────────────

def save_checkpoint(
    version: str,
    metrics: dict,
    pkl_path: str,
    feature_ver: str = "v1",
) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO model_checkpoints
                (version, trained_at, label_count,
                 precision_good, recall_good, f1_good, support_good,
                 promoted, pkl_path, feature_ver)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            version,
            int(time.time()),
            metrics.get("label_count", 0),
            metrics.get("precision_good"),
            metrics.get("recall_good"),
            metrics.get("f1_good"),
            metrics.get("support_good"),
            0,
            pkl_path,
            feature_ver,
        ))


def promote_checkpoint(version: str) -> None:
    """Mark checkpoint as promoted (active model)."""
    with _conn() as conn:
        conn.execute("UPDATE model_checkpoints SET promoted=0")
        conn.execute(
            "UPDATE model_checkpoints SET promoted=1 WHERE version=?",
            (version,)
        )


def get_active_model() -> Optional[dict]:
    """Return the currently promoted model checkpoint, or None."""
    with _conn() as conn:
        row = conn.execute("""
            SELECT * FROM model_checkpoints
            WHERE promoted=1
            ORDER BY trained_at DESC
            LIMIT 1
        """).fetchone()
        return dict(row) if row else None


def next_model_version() -> str:
    """Generate next version string: v1.1, v1.2, ..."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM model_checkpoints"
        ).fetchone()
        n = row["n"] + 1 if row else 1
        return f"v1.{n}"
