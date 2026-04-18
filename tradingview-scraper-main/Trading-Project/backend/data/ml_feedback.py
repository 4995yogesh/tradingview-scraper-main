"""
ml_feedback.py — SQLite-backed feedback loop for consolidation box ML scoring.

Schema
------
boxes     : one row per scored box (written at inference time)
outcomes  : MFE/MAE outcome written after N candles post-box

Outcome tracking formula
------------------------
N = max(20, min(2 × box_duration, 100))
MFE = max(high - box_top) in look-forward window   [% of box_height]
MAE = max(box_bottom - low) in look-forward window  [% of box_height]
outcome_label: GOOD / BAD / NEUTRAL (same thresholds as ML model)
"""

import sqlite3
import logging
import threading
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).resolve().parent / "ml_feedback.db"

# Thread-local storage for connections (avoids cross-thread sharing issues)
_local = threading.local()


# ─────────────────────────────────────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn(db_path: Path) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


# ─────────────────────────────────────────────────────────────────────────────
# Main feedback store class
# ─────────────────────────────────────────────────────────────────────────────

class MLFeedbackStore:
    """
    Thread-safe SQLite store for consolidation box ML feedback.
    Safe to call without a model (all operations degrade gracefully).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or _DEFAULT_DB
        self._lock    = threading.Lock()
        try:
            self._init_db()
            logger.info("MLFeedbackStore: initialized at %s", self._db_path)
        except Exception as e:
            logger.error("MLFeedbackStore: init failed — %s", e)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = _get_conn(self._db_path)
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS boxes (
                    box_id          TEXT PRIMARY KEY,
                    symbol          TEXT NOT NULL,
                    timeframe       TEXT NOT NULL,
                    time_start      INTEGER NOT NULL,   -- unix ms
                    time_end        INTEGER NOT NULL,   -- unix ms
                    price_high      REAL NOT NULL,
                    price_low       REAL NOT NULL,
                    ml_score        REAL,
                    ml_label        TEXT,
                    ml_confidence   REAL,
                    ml_top_features TEXT,               -- JSON
                    recorded_at     TEXT NOT NULL,      -- ISO8601
                    user_label      TEXT,               -- GOOD / BAD / NEUTRAL (human rating)
                    updated_at      TEXT,               -- ISO8601 of last user update
                    is_consumed     BOOLEAN DEFAULT 0   -- 1 if used in ML training
                );

                CREATE TABLE IF NOT EXISTS outcomes (
                    box_id          TEXT PRIMARY KEY,
                    mfe             REAL,
                    mae             REAL,
                    box_height      REAL,
                    outcome_label   TEXT,
                    lookforward_n   INTEGER,
                    computed_at     TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_boxes_unique
                    ON boxes(symbol, timeframe, time_start, time_end);

                CREATE INDEX IF NOT EXISTS idx_boxes_symbol_tf
                    ON boxes(symbol, timeframe);

                CREATE INDEX IF NOT EXISTS idx_boxes_recorded_at
                    ON boxes(recorded_at);
            """)

        # ── Safe migration: add columns if they don't exist (existing DB compat) ─
        existing = [r[1] for r in conn.execute("PRAGMA table_info(boxes)").fetchall()]
        migrations = {
            "user_label":     "ALTER TABLE boxes ADD COLUMN user_label TEXT",
            "updated_at":     "ALTER TABLE boxes ADD COLUMN updated_at TEXT",
            "model_version":  "ALTER TABLE boxes ADD COLUMN model_version TEXT",
            "features_hash":  "ALTER TABLE boxes ADD COLUMN features_hash TEXT",
            "pattern_type":   "ALTER TABLE boxes ADD COLUMN pattern_type TEXT",
            "breakout_direction": "ALTER TABLE boxes ADD COLUMN breakout_direction TEXT",
            "swing_high_1":   "ALTER TABLE boxes ADD COLUMN swing_high_1 FLOAT",
            "swing_low_1":    "ALTER TABLE boxes ADD COLUMN swing_low_1 FLOAT",
            "structure_type": "ALTER TABLE boxes ADD COLUMN structure_type TEXT",
            # ── Detection system columns ──────────────────────────────────────
            "detection_label": "ALTER TABLE boxes ADD COLUMN detection_label TEXT",
            "source":          "ALTER TABLE boxes ADD COLUMN source TEXT DEFAULT 'baseline'",
        }
        with conn:
            for col, sql in migrations.items():
                if col not in existing:
                    conn.execute(sql)
                    logger.info("MLFeedbackStore: migrated boxes — added %s", col)

    # ── Box ID helper ─────────────────────────────────────────────────────────

    @staticmethod
    def make_box_id(symbol: str, timeframe: str, time_start: int, time_end: int) -> str:
        """Deterministic ID so the same box is never double-inserted."""
        raw = f"{symbol}|{timeframe}|{time_start}|{time_end}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    # ── Write ─────────────────────────────────────────────────────────────────

    def record_box(self, zone: Dict[str, Any]) -> Optional[str]:
        """
        Insert one scored zone into boxes table.
        Silently skips if box_id already exists (idempotent).
        Returns box_id if written, None on error.
        """
        import json

        try:
            symbol     = zone.get("timeframe", "?")   # note: zone has 'timeframe' not 'symbol'
            # Caller must pass symbol explicitly — used from server.py
            symbol     = zone.get("symbol", "EURUSD")
            timeframe  = zone.get("timeframe", "?")
            time_start = int(zone.get("timeStart", 0))
            time_end   = int(zone.get("timeEnd", 0))

            box_id = self.make_box_id(symbol, timeframe, time_start, time_end)

            top_feats_json = json.dumps(zone.get("ml_top_features") or [])

            with self._lock:
                conn = _get_conn(self._db_path)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO boxes
                        (box_id, symbol, timeframe, time_start, time_end,
                         price_high, price_low, ml_score, ml_label, ml_confidence,
                         ml_top_features, recorded_at,
                         breakout_direction, swing_high_1, swing_low_1, structure_type)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        box_id, symbol, timeframe, time_start, time_end,
                        float(zone.get("priceHigh", 0)),
                        float(zone.get("priceLow",  0)),
                        float(zone.get("ml_score",  0.5)),
                        str(zone.get("ml_label",  "NEUTRAL")),
                        float(zone.get("ml_confidence", 0.0)),
                        top_feats_json,
                        datetime.now(timezone.utc).isoformat(),
                        zone.get("breakout_direction"),
                        zone.get("swing_high_1"),
                        zone.get("swing_low_1"),
                        zone.get("structure_type"),
                    ),
                )
                conn.commit()
            return box_id
        except Exception as e:
            logger.warning("MLFeedbackStore.record_box failed: %s", e)
            return None

    # ── Outcome update ────────────────────────────────────────────────────────

    def update_outcome(
        self,
        box_id: str,
        mfe: float,
        mae: float,
        lookforward_n: int,
        outcome_label: str = "NEUTRAL",
    ) -> bool:
        """
        Write MFE/MAE outcome for a previously recorded box.
        outcome_label: GOOD / BAD / NEUTRAL (derived from MFE vs MAE ratio).
        Returns True on success.
        """
        try:
            with self._lock:
                conn = _get_conn(self._db_path)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO outcomes
                        (box_id, mfe, mae, outcome_label, lookforward_n, computed_at)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        box_id,
                        round(mfe, 6),
                        round(mae, 6),
                        outcome_label,
                        lookforward_n,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.warning("MLFeedbackStore.update_outcome failed: %s", e)
            return False

    # ── Outcome computation ───────────────────────────────────────────────────

    def update_user_feedback(
        self,
        box_id: str,
        user_label: str,
    ) -> bool:
        """
        Store human rating for an existing box (idempotent).

        Rules:
          - ONLY updates — never inserts. box_id must already exist.
          - user_label must be GOOD / BAD / NEUTRAL.
          - If existing user_label == user_label → no-op, returns True (idempotent).
          - Returns False if box_id not found or label invalid.
        """
        VALID = {"GOOD", "BAD", "NEUTRAL"}
        if user_label not in VALID:
            logger.warning("update_user_feedback: invalid label %r", user_label)
            return False

        try:
            with self._lock:
                conn = _get_conn(self._db_path)

                # Idempotent check: read current value first
                existing_row = conn.execute(
                    "SELECT user_label FROM boxes WHERE box_id = ?", (box_id,)
                ).fetchone()

                if existing_row is None:
                    logger.warning("update_user_feedback: box_id %s not found", box_id)
                    return False

                if existing_row[0] == user_label:
                    logger.debug("update_user_feedback: no-op for %s (already %s)", box_id, user_label)
                    return True   # already set — no write needed

                conn.execute(
                    "UPDATE boxes SET user_label = ?, updated_at = ? WHERE box_id = ?",
                    (user_label, datetime.now(timezone.utc).isoformat(), box_id),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.warning("update_user_feedback failed: %s", e)
            return False

    def update_pattern_type(
        self,
        box_id: str,
        pattern_type: str,
    ) -> bool:
        """
        Store pattern type (CONTINUATION / LIQUIDITY_GRAB) for an existing box (idempotent).
        """
        VALID = {"CONTINUATION", "LIQUIDITY_GRAB"}
        if pattern_type not in VALID:
            logger.warning("update_pattern_type: invalid label %r", pattern_type)
            return False

        try:
            with self._lock:
                conn = _get_conn(self._db_path)
                
                existing_row = conn.execute(
                    "SELECT pattern_type FROM boxes WHERE box_id = ?", (box_id,)
                ).fetchone()

                if existing_row is None:
                    logger.warning("update_pattern_type: box_id %s not found", box_id)
                    return False

                if existing_row[0] == pattern_type:
                    return True
                
                conn.execute(
                    "UPDATE boxes SET pattern_type = ?, updated_at = ? WHERE box_id = ?",
                    (pattern_type, datetime.now(timezone.utc).isoformat(), box_id),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.warning("update_pattern_type failed: %s", e)
            return False

    # ── Detection system helpers ───────────────────────────────────────────────

    def update_detection_label(self, box_id: str, label: str) -> bool:
        """
        Store detection feedback (RIGHT / WRONG / IGNORE) for a box.
        Box must already exist (created at inference time by record_box).
        Idempotent — no-op if label unchanged.
        """
        VALID = {"RIGHT", "WRONG", "IGNORE"}
        label = label.strip().upper()
        if label not in VALID:
            logger.warning("update_detection_label: invalid label %r", label)
            return False
        try:
            with self._lock:
                conn = _get_conn(self._db_path)
                row = conn.execute(
                    "SELECT detection_label FROM boxes WHERE box_id = ?", (box_id,)
                ).fetchone()
                if row is None:
                    logger.warning("update_detection_label: box_id %s not found", box_id)
                    return False
                if row[0] == label:
                    return True
                conn.execute(
                    "UPDATE boxes SET detection_label = ?, updated_at = ? WHERE box_id = ?",
                    (label, datetime.now(timezone.utc).isoformat(), box_id),
                )
                conn.commit()
            logger.info("Detection label: %s → %s", box_id, label)
            return True
        except Exception as e:
            logger.warning("update_detection_label failed: %s", e)
            return False

    def insert_manual_box(self, zone: Dict[str, Any]) -> Optional[str]:
        """
        Insert a user-drawn box with detection_label=RIGHT and source=manual.
        These are treated as high-quality positives in training.
        Returns box_id on success, None on error.
        """
        try:
            symbol    = zone.get("symbol", "EURUSD")
            timeframe = zone.get("timeframe", "?")
            ts        = int(zone.get("timeStart", 0))
            te        = int(zone.get("timeEnd",   0))
            box_id    = self.make_box_id(symbol, timeframe, ts, te)

            with self._lock:
                conn = _get_conn(self._db_path)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO boxes
                        (box_id, symbol, timeframe, time_start, time_end,
                         price_high, price_low,
                         ml_score, ml_label, ml_confidence, ml_top_features,
                         recorded_at, detection_label, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        box_id, symbol, timeframe, ts, te,
                        float(zone.get("priceHigh", 0)),
                        float(zone.get("priceLow", 0)),
                        0.5, "NEUTRAL", 0.0, "[]",
                        datetime.now(timezone.utc).isoformat(),
                        "RIGHT",
                        "manual",
                    ),
                )
                conn.commit()
            logger.info("Manual box inserted: %s [%s %s]", box_id, symbol, timeframe)
            return box_id
        except Exception as e:
            logger.warning("insert_manual_box failed: %s", e)
            return None

    def get_detection_dataset(self) -> List[Dict[str, Any]]:
        """
        Return all labeled boxes (RIGHT or WRONG) for detection model training.
        Ordered by recorded_at ascending (oldest first) to support temporal split.
        """
        try:
            conn = _get_conn(self._db_path)
            rows = conn.execute("""
                SELECT box_id, symbol, timeframe, time_start, time_end,
                       price_high, price_low, detection_label, source, recorded_at
                FROM boxes
                WHERE detection_label IN ('RIGHT', 'WRONG')
                ORDER BY recorded_at ASC
            """).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("get_detection_dataset failed: %s", e)
            return []

    # ── Disagreement analysis ─────────────────────────────────────────────────


    def analyze_disagreement(self) -> Dict[str, Any]:
        """
        Compare ml_label vs user_label vs outcome_label for all rated boxes.

        Classification rules (only for boxes with both user_label + outcome_label):

          AGREEMENT_CORRECT : ml == user == outcome
          MODEL_WRONG       : ml ≠ outcome AND user == outcome
          USER_WRONG        : user ≠ outcome AND ml == outcome
          BOTH_WRONG        : ml ≠ outcome AND user ≠ outcome
          UNVERIFIED        : outcome missing (no lookforward data yet)
          UNRATED           : user_label missing

        Returns:
          counts per class, agreement_pct, model_accuracy, user_accuracy,
          disagreement_count (ml_label ≠ user_label), total_rated
        """
        try:
            conn = _get_conn(self._db_path)
            rows = conn.execute("""
                SELECT b.box_id, b.ml_label, b.user_label, o.outcome_label
                FROM boxes b
                LEFT JOIN outcomes o ON b.box_id = o.box_id
                WHERE b.ml_label IS NOT NULL
            """).fetchall()

            counts: Dict[str, int] = {
                "AGREEMENT_CORRECT": 0,
                "MODEL_WRONG":       0,
                "USER_WRONG":        0,
                "BOTH_WRONG":        0,
                "UNVERIFIED":        0,
                "UNRATED":           0,
            }
            ml_correct = ml_total = 0
            usr_correct = usr_total = 0
            disagreements: List[str] = []  # box_ids where ml ≠ user

            for box_id, ml_label, user_label, outcome_label in rows:
                if user_label is None:
                    counts["UNRATED"] += 1
                    continue

                if ml_label != user_label:
                    disagreements.append(box_id)

                if outcome_label is None:
                    counts["UNVERIFIED"] += 1
                    continue

                # Track model accuracy
                ml_total += 1
                if ml_label == outcome_label:
                    ml_correct += 1

                # Track user accuracy
                usr_total += 1
                if user_label == outcome_label:
                    usr_correct += 1

                # Classify
                ml_ok  = (ml_label   == outcome_label)
                usr_ok = (user_label == outcome_label)

                if ml_ok and usr_ok:
                    counts["AGREEMENT_CORRECT"] += 1
                elif not ml_ok and usr_ok:
                    counts["MODEL_WRONG"] += 1
                elif usr_ok is False and ml_ok:
                    counts["USER_WRONG"] += 1
                else:
                    counts["BOTH_WRONG"] += 1

            total_rated   = len(rows) - counts["UNRATED"]
            total_verified = ml_total  # rows with both user_label + outcome

            agreement_pct = (
                round((len(rows) - counts["UNRATED"] - len(disagreements)) /
                      max(1, total_rated) * 100, 1)
                if total_rated > 0 else None
            )

            return {
                "counts":             counts,
                "total_rated":        total_rated,
                "total_verified":     total_verified,
                "disagreement_count": len(disagreements),
                "disagreement_box_ids": disagreements,
                "agreement_pct":      agreement_pct,
                # Accuracy computed ONLY over verified rows (outcome NOT NULL)
                "model_accuracy":     round(ml_correct  / ml_total  * 100, 1) if ml_total  > 0 else None,
                "user_accuracy":      round(usr_correct / usr_total * 100, 1) if usr_total > 0 else None,
            }
        except Exception as e:
            logger.warning("analyze_disagreement failed: %s", e)
            return {"error": str(e)}

    # ── Precision metric ────────────────────────────────────────────────────────────────

    def precision_at(
        self,
        threshold: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Precision of the ML model at a given score threshold.

        Filters: ml_score >= threshold AND outcome_label IS NOT NULL
        Excludes: NEUTRAL outcomes (ambiguous — not actionable)

        precision = GOOD_outcomes / (GOOD_outcomes + BAD_outcomes)

        Interpretation:
          High precision @ 0.6 means boxes the model is confident about
          actually broke out (GOOD) vs reversed (BAD) more often.

        Returns: {threshold, precision, good_count, bad_count, sample_size}
        """
        try:
            conn = _get_conn(self._db_path)
            rows = conn.execute("""
                SELECT o.outcome_label
                FROM   boxes b
                JOIN   outcomes o ON b.box_id = o.box_id
                WHERE  b.ml_score >= ?
                  AND  o.outcome_label IS NOT NULL
                  AND  o.outcome_label IN ('GOOD', 'BAD')
            """, (threshold,)).fetchall()

            good_count = sum(1 for (lbl,) in rows if lbl == "GOOD")
            bad_count  = sum(1 for (lbl,) in rows if lbl == "BAD")
            total      = good_count + bad_count

            precision = round(good_count / total * 100, 1) if total > 0 else None

            return {
                "threshold":   threshold,
                "precision":   precision,
                "good_count":  good_count,
                "bad_count":   bad_count,
                "sample_size": total,
            }
        except Exception as e:
            logger.warning("precision_at failed: %s", e)
            return {"threshold": threshold, "precision": None, "sample_size": 0, "error": str(e)}

    # ── Outcome label logic ───────────────────────────────────────────────────

    @staticmethod
    def compute_outcome_label(mfe: float, mae: float, box_height: float = 0.0) -> str:
        """
        Upgraded outcome labeling (v4.1).

        mfe, mae — max favourable/adverse excursion as FRACTION of box_height.
        Logic:
          1. move = max(|mfe|, |mae|)
          2. If move < 0.5 → NEUTRAL  (price barely moved)
          3. ratio = mfe / (mae + ε)
             >= 2.0 → GOOD   <= 0.5 → BAD   else → NEUTRAL
        """
        eps = 1e-9
        move = max(abs(mfe), abs(mae))
        if move < 0.5:
            return "NEUTRAL"
        ratio = mfe / (mae + eps)
        if ratio >= 2.0:
            return "GOOD"
        if ratio <= 0.5:
            return "BAD"
        return "NEUTRAL"

    # ── Rich summary ────────────────────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """
        Returns detailed feedback statistics for analysis / retraining decisions.

        Returns:
          total_boxes       : total boxes recorded
          good_count        : outcome labeled GOOD
          bad_count         : outcome labeled BAD
          neutral_count     : outcome labeled NEUTRAL
          pending_count     : boxes with no outcome yet
          avg_score_good    : mean ml_score for GOOD outcomes
          avg_score_bad     : mean ml_score for BAD outcomes
          avg_score_neutral : mean ml_score for NEUTRAL outcomes
          label_accuracy    : % where ml_label matches outcome_label
        """
        try:
            conn = _get_conn(self._db_path)

            total_boxes = conn.execute("SELECT COUNT(*) FROM boxes").fetchone()[0]

            rows = conn.execute("""
                SELECT b.ml_score, b.ml_label, o.outcome_label
                FROM boxes b
                LEFT JOIN outcomes o ON b.box_id = o.box_id
            """).fetchall()

            good_count = bad_count = neutral_count = pending_count = 0
            score_good: List[float] = []
            score_bad:  List[float] = []
            score_neutral: List[float] = []
            label_match = label_total = 0

            for ml_score, ml_label, outcome_label in rows:
                if outcome_label is None:
                    pending_count += 1
                    continue
                if outcome_label == "GOOD":
                    good_count += 1
                    if ml_score is not None:
                        score_good.append(ml_score)
                elif outcome_label == "BAD":
                    bad_count += 1
                    if ml_score is not None:
                        score_bad.append(ml_score)
                else:
                    neutral_count += 1
                    if ml_score is not None:
                        score_neutral.append(ml_score)

                if ml_label and outcome_label:
                    label_total += 1
                    if ml_label == outcome_label:
                        label_match += 1

            avg = lambda lst: round(sum(lst) / len(lst), 4) if lst else None
            accuracy = round(label_match / label_total, 4) if label_total > 0 else None

            return {
                "total_boxes":       total_boxes,
                "good_count":        good_count,
                "bad_count":         bad_count,
                "neutral_count":     neutral_count,
                "pending_count":     pending_count,
                "avg_score_good":    avg(score_good),
                "avg_score_bad":     avg(score_bad),
                "avg_score_neutral": avg(score_neutral),
                "label_accuracy":    accuracy,
                "db_path":           str(self._db_path),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Labeled list ─────────────────────────────────────────────────────────

    def get_labeled_list(self) -> List[Dict[str, Any]]:
        """
        Return all boxes with a user_label (GOOD/BAD/NEUTRAL), newest first.
        Used by /api/ml/labeled-list to power the sidebar panel.
        """
        try:
            conn = _get_conn(self._db_path)
            rows = conn.execute("""
                SELECT box_id, symbol, timeframe, time_start, time_end,
                       price_high, price_low,
                       user_label, pattern_type, updated_at, recorded_at,
                       COALESCE(is_consumed, 0) AS is_consumed
                FROM boxes
                WHERE user_label IS NOT NULL
                ORDER BY COALESCE(updated_at, recorded_at) DESC
            """).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("get_labeled_list failed: %s", e)
            return []

    def count_user_labeled(self) -> int:
        """Fast count of boxes with any user_label."""
        try:
            conn = _get_conn(self._db_path)
            return conn.execute(
                "SELECT COUNT(*) FROM boxes WHERE user_label IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            return 0

    # ── Diagnostics alias (backward-compat) ──────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Backward-compatible alias — delegates to get_summary()."""
        return self.get_summary()


# ─────────────────────────────────────────────────────────────────────────────
# Outcome tracker — run post-inference to compute MFE/MAE for past boxes
# ─────────────────────────────────────────────────────────────────────────────

def compute_box_outcome(
    ohlc_df,            # pd.DataFrame with columns: high, low
    box_start_idx: int,
    box_end_idx: int,
    price_high: float,
    price_low: float,
) -> Dict[str, Any]:
    """
    Compute MFE/MAE for a completed box using post-box look-forward.

    Look-forward N = max(20, min(2 × box_duration, 100))
    MFE = max move ABOVE box_high in window / box_height
    MAE = max move BELOW box_low  in window / box_height

    Returns: {mfe, mae, box_height, lookforward_n, outcome_label}
    """
    box_height = price_high - price_low
    if box_height <= 0:
        return {"mfe": 0.0, "mae": 0.0, "box_height": 0.0,
                "lookforward_n": 0, "outcome_label": "NEUTRAL"}

    box_duration  = max(1, box_end_idx - box_start_idx)
    lookforward_n = max(20, min(2 * box_duration, 100))

    n_total  = len(ohlc_df)
    lf_start = box_end_idx + 1
    lf_end   = min(lf_start + lookforward_n, n_total)

    if lf_start >= n_total:
        return {"mfe": 0.0, "mae": 0.0, "box_height": round(box_height, 6),
                "lookforward_n": lookforward_n, "outcome_label": "NEUTRAL"}

    window   = ohlc_df.iloc[lf_start:lf_end]
    max_high = float(window["high"].max())
    min_low  = float(window["low"].min())

    mfe = max(0.0, (max_high - price_high) / box_height)
    mae = max(0.0, (price_low  - min_low)  / box_height)

    # Pass box_height for future per-box normalization if needed
    label = MLFeedbackStore.compute_outcome_label(mfe, mae, box_height=box_height)

    return {
        "mfe":           round(mfe, 6),
        "mae":           round(mae, 6),
        "box_height":    round(box_height, 6),
        "lookforward_n": lookforward_n,
        "outcome_label": label,
    }


def suggest_pattern_type(ohlc_df, box_end_idx: int, price_high: float, price_low: float) -> dict:
    """
    Deterministic structure-based pattern classification.
    Returns dict with swing features and pattern_suggestion.
    """
    res = {
        "breakout_direction": None,
        "pattern_suggestion": None,
        "structure_type": None,
        "swing_count": 0,
        "swing_high_1": None,
        "swing_low_1": None,
        "first_pullback_depth": None,
        "time_to_structure_break": None,
        "structure_strength": None
    }
    
    n = len(ohlc_df)
    if box_end_idx + 1 >= n:
        return res
        
    # STEP 1 - Detect breakout
    breakout_dir = None
    breakout_idx = None
    
    for i in range(box_end_idx + 1, n):
        c = float(ohlc_df["close"].iloc[i])
        if c > price_high:
            breakout_dir = "bullish"
            breakout_idx = i
            break
        elif c < price_low:
            breakout_dir = "bearish"
            breakout_idx = i
            break
            
    if not breakout_dir:
        return res
        
    res["breakout_direction"] = breakout_dir

    def is_pivot_high(idx):
        if idx - 1 < 0 or idx + 1 >= n: return False
        return ohlc_df["high"].iloc[idx] > ohlc_df["high"].iloc[idx-1] and \
               ohlc_df["high"].iloc[idx] > ohlc_df["high"].iloc[idx+1]
               
    def is_pivot_low(idx):
        if idx - 1 < 0 or idx + 1 >= n: return False
        return ohlc_df["low"].iloc[idx] < ohlc_df["low"].iloc[idx-1] and \
               ohlc_df["low"].iloc[idx] < ohlc_df["low"].iloc[idx+1]

    def count_swings(start_idx, end_idx):
        sw = 0
        for i in range(start_idx, end_idx):
            if is_pivot_high(i) or is_pivot_low(i): sw += 1
        return sw

    # STEP 2 & 3 & 4
    if breakout_dir == "bullish":
        ph_idx = None
        for i in range(breakout_idx, n - 1):
            if is_pivot_high(i):
                ph_idx = i
                break
        if ph_idx is None: return res
        
        pl_idx = None
        for i in range(ph_idx + 1, n - 1):
            if is_pivot_low(i):
                pl_idx = i
                break
        if pl_idx is None: return res
        
        pb_high = float(ohlc_df["high"].iloc[ph_idx])
        pb_low = float(ohlc_df["low"].iloc[pl_idx])
        
        res["swing_high_1"] = pb_high
        res["swing_low_1"] = pb_low
        res["first_pullback_depth"] = round(pb_high - pb_low, 6)
        
        for i in range(pl_idx + 1, n):
            h = float(ohlc_df["high"].iloc[i])
            l = float(ohlc_df["low"].iloc[i])
            
            break_high = h > pb_high
            break_low = l < pb_low
            
            if break_high and break_low:
                res["swing_count"] = count_swings(breakout_idx, i)
                return res
            if break_high:
                res["structure_type"] = "HH-HL"
                res["pattern_suggestion"] = "CONTINUATION"
                res["time_to_structure_break"] = i - breakout_idx
                # structure strength max move after break
                sub = ohlc_df["high"].iloc[i:min(i+20, n)]
                res["structure_strength"] = round(float(sub.max()) - h, 6) if len(sub)>0 else 0
                res["swing_count"] = count_swings(breakout_idx, i)
                return res
            if break_low:
                res["structure_type"] = "HH-LH" # (liquidity)
                res["pattern_suggestion"] = "LIQUIDITY_GRAB"
                res["time_to_structure_break"] = i - breakout_idx
                sub = ohlc_df["low"].iloc[i:min(i+20, n)]
                res["structure_strength"] = round(l - float(sub.min()), 6) if len(sub)>0 else 0
                res["swing_count"] = count_swings(breakout_idx, i)
                return res
                
        res["swing_count"] = count_swings(breakout_idx, n)
        return res
        
    elif breakout_dir == "bearish":
        pl_idx = None
        for i in range(breakout_idx, n - 1):
            if is_pivot_low(i):
                pl_idx = i
                break
        if pl_idx is None: return res
        
        ph_idx = None
        for i in range(pl_idx + 1, n - 1):
            if is_pivot_high(i):
                ph_idx = i
                break
        if ph_idx is None: return res
        
        pb_low = float(ohlc_df["low"].iloc[pl_idx])
        pb_high = float(ohlc_df["high"].iloc[ph_idx])
        
        res["swing_low_1"] = pb_low
        res["swing_high_1"] = pb_high
        res["first_pullback_depth"] = round(pb_high - pb_low, 6)
        
        for i in range(ph_idx + 1, n):
            h = float(ohlc_df["high"].iloc[i])
            l = float(ohlc_df["low"].iloc[i])
            
            break_low = l < pb_low
            break_high = h > pb_high
            
            if break_low and break_high:
                res["swing_count"] = count_swings(breakout_idx, i)
                return res
            if break_low:
                res["structure_type"] = "LL-LH"
                res["pattern_suggestion"] = "CONTINUATION"
                res["time_to_structure_break"] = i - breakout_idx
                sub = ohlc_df["low"].iloc[i:min(i+20, n)]
                res["structure_strength"] = round(l - float(sub.min()), 6) if len(sub)>0 else 0
                res["swing_count"] = count_swings(breakout_idx, i)
                return res
            if break_high:
                res["structure_type"] = "LL-HL" # (liquidity)
                res["pattern_suggestion"] = "LIQUIDITY_GRAB"
                res["time_to_structure_break"] = i - breakout_idx
                sub = ohlc_df["high"].iloc[i:min(i+20, n)]
                res["structure_strength"] = round(float(sub.max()) - h, 6) if len(sub)>0 else 0
                res["swing_count"] = count_swings(breakout_idx, i)
                return res
                
        res["swing_count"] = count_swings(breakout_idx, n)
        return res


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────
feedback_store = MLFeedbackStore()
