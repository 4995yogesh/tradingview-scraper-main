"""
Pattern Memory Database — Phase 2
SQLite persistence layer for TimeFM embeddings + pattern outcomes.
"""
from __future__ import annotations

import os
import sqlite3
import time
import json
import hashlib
import logging
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

# Current embedding version — bump when model or window design changes
EMBEDDING_VERSION = "timesfm-2.5-fp32-v1"

# Default DB path — same directory as this file
_DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pattern_memory.db")


@dataclass
class PatternRecord:
    """Full pattern record stored in pattern_memory.db."""

    # Identity
    pattern_id:         str = ""
    box_id:             str = ""
    symbol:             str = ""
    exchange:           str = "OANDA"
    timeframe:          str = ""

    # Box geometry
    box_time_start:     int   = 0
    box_time_end:       int   = 0
    price_high:         float = 0.0
    price_low:          float = 0.0
    box_width_candles:  int   = 0

    # Detection quality
    quality_score:      float = 0.0
    is_valid:           int   = 0
    detection_confidence: float = 0.0

    # Embedding
    embedding_version:  str = EMBEDDING_VERSION
    embedding_dim:      int = 0
    embedding:          Optional[np.ndarray] = field(default=None, repr=False)

    # Window
    context_pre_candles:  int = 50
    context_post_candles: int = 0
    window_total_candles: int = 0

    # Outcomes (populated by outcome_harvester later)
    breakout_direction:   Optional[str]   = None
    breakout_strength:    Optional[float] = None
    breakout_confirmed:   Optional[int]   = None
    future_return_10:     Optional[float] = None
    future_return_20:     Optional[float] = None
    future_return_50:     Optional[float] = None
    future_return_100:    Optional[float] = None
    mfe:                  Optional[float] = None
    mae:                  Optional[float] = None
    time_to_breakout:     Optional[int]   = None
    post_breakout_follow: Optional[float] = None

    # Pattern context
    atr_at_box_end:               Optional[float] = None
    box_height_atr:               Optional[float] = None
    consolidation_duration_score: Optional[float] = None

    # Recommended extra fields
    session_time_of_day: Optional[str] = None   # "london","ny","asian","overlap"
    day_of_week:         Optional[int] = None   # 0-4
    htf_bias:            Optional[str] = None   # "bullish","bearish","neutral"

    # Metadata
    source:             str = "labeled"         # "labeled","auto_labeled","backfill"
    human_reviewed:     int = 0
    created_at:         int = 0
    outcome_computed_at: Optional[int] = None

    def make_pattern_id(self) -> str:
        key = f"{self.box_id}::{self.embedding_version}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def to_summary(self) -> Dict[str, Any]:
        """Return a compact JSON-serialisable dict (no embedding blob)."""
        return {
            "pattern_id":        self.pattern_id,
            "box_id":            self.box_id,
            "symbol":            self.symbol,
            "timeframe":         self.timeframe,
            "box_time_start":    self.box_time_start,
            "box_time_end":      self.box_time_end,
            "price_high":        self.price_high,
            "price_low":         self.price_low,
            "quality_score":     self.quality_score,
            "breakout_direction":self.breakout_direction,
            "future_return_20":  self.future_return_20,
            "win":               (self.future_return_20 or 0) > 0.0015,
            "mfe":               self.mfe,
            "mae":               self.mae,
        }


class PatternMemoryDB:
    """SQLite persistence layer for pattern embeddings and outcomes."""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id               TEXT PRIMARY KEY,
                    box_id                   TEXT NOT NULL,
                    symbol                   TEXT NOT NULL,
                    exchange                 TEXT NOT NULL DEFAULT 'OANDA',
                    timeframe                TEXT NOT NULL,

                    box_time_start           INTEGER NOT NULL,
                    box_time_end             INTEGER NOT NULL,
                    price_high               REAL NOT NULL,
                    price_low                REAL NOT NULL,
                    box_width_candles        INTEGER NOT NULL DEFAULT 0,

                    quality_score            REAL NOT NULL DEFAULT 0.0,
                    is_valid                 INTEGER NOT NULL DEFAULT 0,
                    detection_confidence     REAL DEFAULT 0.0,

                    embedding_version        TEXT NOT NULL,
                    embedding_dim            INTEGER NOT NULL,
                    embedding                BLOB NOT NULL,

                    context_pre_candles      INTEGER DEFAULT 50,
                    context_post_candles     INTEGER DEFAULT 0,
                    window_total_candles     INTEGER NOT NULL DEFAULT 0,

                    breakout_direction       TEXT,
                    breakout_strength        REAL,
                    breakout_confirmed       INTEGER,
                    future_return_10         REAL,
                    future_return_20         REAL,
                    future_return_50         REAL,
                    future_return_100        REAL,
                    mfe                      REAL,
                    mae                      REAL,
                    time_to_breakout         INTEGER,
                    post_breakout_follow     REAL,

                    atr_at_box_end           REAL,
                    box_height_atr           REAL,
                    consolidation_duration_score REAL,

                    session_time_of_day      TEXT,
                    day_of_week              INTEGER,
                    htf_bias                 TEXT,

                    source                   TEXT DEFAULT 'labeled',
                    human_reviewed           INTEGER DEFAULT 0,
                    created_at               INTEGER NOT NULL,
                    outcome_computed_at      INTEGER,

                    UNIQUE(box_id, embedding_version)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_box_id
                ON patterns(box_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_symbol_tf
                ON patterns(symbol, timeframe)
            """)
            conn.commit()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Write ──────────────────────────────────────────────────────────────────

    def insert_pattern(self, rec: PatternRecord) -> str:
        """
        Insert or replace a pattern record.
        Returns the pattern_id.
        """
        if not rec.pattern_id:
            rec.pattern_id = rec.make_pattern_id()
        if not rec.created_at:
            rec.created_at = int(time.time())

        emb_bytes = rec.embedding.astype(np.float32).tobytes() if rec.embedding is not None else b""
        emb_dim   = rec.embedding.shape[0] if rec.embedding is not None else 0

        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO patterns (
                    pattern_id, box_id, symbol, exchange, timeframe,
                    box_time_start, box_time_end, price_high, price_low, box_width_candles,
                    quality_score, is_valid, detection_confidence,
                    embedding_version, embedding_dim, embedding,
                    context_pre_candles, context_post_candles, window_total_candles,
                    breakout_direction, breakout_strength, breakout_confirmed,
                    future_return_10, future_return_20, future_return_50, future_return_100,
                    mfe, mae, time_to_breakout, post_breakout_follow,
                    atr_at_box_end, box_height_atr, consolidation_duration_score,
                    session_time_of_day, day_of_week, htf_bias,
                    source, human_reviewed, created_at, outcome_computed_at
                ) VALUES (
                    ?,?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,?
                )
            """, (
                rec.pattern_id, rec.box_id, rec.symbol, rec.exchange, rec.timeframe,
                rec.box_time_start, rec.box_time_end, rec.price_high, rec.price_low, rec.box_width_candles,
                rec.quality_score, rec.is_valid, rec.detection_confidence,
                rec.embedding_version, emb_dim, emb_bytes,
                rec.context_pre_candles, rec.context_post_candles, rec.window_total_candles,
                rec.breakout_direction, rec.breakout_strength, rec.breakout_confirmed,
                rec.future_return_10, rec.future_return_20, rec.future_return_50, rec.future_return_100,
                rec.mfe, rec.mae, rec.time_to_breakout, rec.post_breakout_follow,
                rec.atr_at_box_end, rec.box_height_atr, rec.consolidation_duration_score,
                rec.session_time_of_day, rec.day_of_week, rec.htf_bias,
                rec.source, rec.human_reviewed, rec.created_at, rec.outcome_computed_at,
            ))
            conn.commit()
        return rec.pattern_id

    def update_outcomes(self, box_id: str, outcomes: dict):
        """Update outcome fields for all patterns with the given box_id."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE patterns SET
                    breakout_direction   = ?,
                    breakout_strength    = ?,
                    breakout_confirmed   = ?,
                    future_return_10     = ?,
                    future_return_20     = ?,
                    future_return_50     = ?,
                    future_return_100    = ?,
                    mfe                  = ?,
                    mae                  = ?,
                    time_to_breakout     = ?,
                    post_breakout_follow = ?,
                    atr_at_box_end       = ?,
                    box_height_atr       = ?,
                    outcome_computed_at  = ?
                WHERE box_id = ?
            """, (
                outcomes.get("breakout_direction"),
                outcomes.get("breakout_strength"),
                outcomes.get("breakout_confirmed"),
                outcomes.get("future_return_10"),
                outcomes.get("future_return_20"),
                outcomes.get("future_return_50"),
                outcomes.get("future_return_100"),
                outcomes.get("mfe"),
                outcomes.get("mae"),
                outcomes.get("time_to_breakout"),
                outcomes.get("post_breakout_follow"),
                outcomes.get("atr_at_box_end"),
                outcomes.get("box_height_atr"),
                int(time.time()),
                box_id,
            ))
            conn.commit()

    # ── Read ───────────────────────────────────────────────────────────────────

    def _row_to_record(self, row) -> PatternRecord:
        d = dict(row)
        emb_bytes = d.pop("embedding", b"")
        emb_dim   = d.get("embedding_dim", 0)
        if emb_bytes and emb_dim > 0:
            emb = np.frombuffer(emb_bytes, dtype=np.float32).copy()
        else:
            emb = None
        rec = PatternRecord(**{k: d[k] for k in d if k in PatternRecord.__dataclass_fields__})
        rec.embedding = emb
        return rec

    def get_pattern_by_id(self, pattern_id: str) -> Optional[PatternRecord]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM patterns WHERE pattern_id = ?", (pattern_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def get_patterns_by_ids(self, pattern_ids: List[str]) -> List[PatternRecord]:
        if not pattern_ids:
            return []
        placeholders = ",".join("?" * len(pattern_ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM patterns WHERE pattern_id IN ({placeholders})",
                pattern_ids
            ).fetchall()
        # Preserve order matching pattern_ids
        by_id = {dict(r)["pattern_id"]: self._row_to_record(r) for r in rows}
        return [by_id[pid] for pid in pattern_ids if pid in by_id]

    def get_all_embeddings(self, version: str = EMBEDDING_VERSION) -> tuple:
        """
        Returns (pattern_ids, embeddings_matrix) where:
          pattern_ids: List[str]
          embeddings_matrix: np.ndarray [N, D]  (L2-normalized float32)
        Only returns patterns with embedding_version == version.
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT pattern_id, embedding, embedding_dim
                FROM patterns
                WHERE embedding_version = ? AND embedding IS NOT NULL AND embedding_dim > 0
            """, (version,)).fetchall()

        if not rows:
            return [], np.empty((0, 0), dtype=np.float32)

        ids = []
        embs = []
        for row in rows:
            pid = row[0]
            emb_bytes = row[1]
            emb_dim   = row[2]
            emb = np.frombuffer(emb_bytes, dtype=np.float32).copy()
            if emb.shape[0] == emb_dim and emb_dim > 0:
                ids.append(pid)
                embs.append(emb)

        if not embs:
            return [], np.empty((0, 0), dtype=np.float32)

        matrix = np.stack(embs, axis=0)   # [N, D]
        return ids, matrix

    def get_patterns_with_outcomes(self, version: str = EMBEDDING_VERSION) -> List[PatternRecord]:
        """Returns patterns that have outcomes computed."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM patterns
                WHERE embedding_version = ?
                  AND outcome_computed_at IS NOT NULL
                  AND future_return_20 IS NOT NULL
            """, (version,)).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count(self, version: str = EMBEDDING_VERSION) -> dict:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM patterns WHERE embedding_version = ?", (version,)
            ).fetchone()[0]
            with_outcomes = conn.execute("""
                SELECT COUNT(*) FROM patterns
                WHERE embedding_version = ? AND outcome_computed_at IS NOT NULL
            """, (version,)).fetchone()[0]
        return {"total": total, "with_outcomes": with_outcomes}

    def get_stats(self) -> dict:
        stats = self.count()
        with self._conn() as conn:
            # Breakout distribution
            rows = conn.execute("""
                SELECT breakout_direction, COUNT(*) as n
                FROM patterns
                WHERE outcome_computed_at IS NOT NULL
                GROUP BY breakout_direction
            """).fetchall()
            stats["breakout_distribution"] = {r[0] or "NULL": r[1] for r in rows}
            # Avg quality
            row = conn.execute("SELECT AVG(quality_score) FROM patterns").fetchone()
            stats["avg_quality_score"] = round(row[0] or 0, 3)
        return stats
