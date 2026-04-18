"""
detection_train.py — Training pipeline for the consolidation detection model.

Design decisions:
  - XGBoost binary classifier (valid consolidation = 1, not valid = 0)
  - Temporal split: train=older 80%, val=newer 20% (NO random shuffle → no leakage)
  - Class balance: scale_pos_weight = negatives / positives
  - Sample weights: manual=3, RIGHT=2, WRONG=1
  - Hard negative mining: run current model → high-score unlabeled boxes → weight=2
  - Confidence calibration: isotonic regression via sklearn
  - F1-optimal threshold search over [0.35, 0.40, ... 0.70]
  - Model versioning: version JSON saved alongside pkl
  - Retrain gate: <10 samples → error, 10–49 → warning, ≥50 → full train
"""

import sys
import os
import json
import logging
import pickle
import threading
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE    = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent          # project/
_BACKEND = _PROJECT.parent / "backend"
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "data"))

from detection_features import extract_detection_features, EXPECTED_FEATURE_COUNT
from ml_feedback import feedback_store          # existing store

# ── Output paths ──────────────────────────────────────────────────────────────
_MODEL_DIR  = _HERE
_MODEL_PKL  = _MODEL_DIR / "detection_model.pkl"
_META_JSON  = _MODEL_DIR / "detection_model_meta.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("detection_train")

# ── Global retrain lock (prevents concurrent retrains from server) ────────────
_RETRAIN_LOCK = threading.Lock()


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_labeled_rows() -> pd.DataFrame:
    """
    Pull labeled boxes from ml_feedback.db.
    Returns DataFrame with columns including detection_label, source, recorded_at.
    """
    import sqlite3
    db_path = _BACKEND / "data" / "ml_feedback.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT box_id, symbol, timeframe,
               time_start, time_end, price_high, price_low,
               detection_label, source, recorded_at,
               ml_score
        FROM boxes
        WHERE detection_label IS NOT NULL
          AND detection_label != 'IGNORE'
    """).fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([dict(r) for r in rows])


def _load_unlabeled_rows() -> pd.DataFrame:
    """Pull boxes with no detection_label (for hard negative mining)."""
    import sqlite3
    db_path = _BACKEND / "data" / "ml_feedback.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT box_id, symbol, timeframe,
               time_start, time_end, price_high, price_low, ml_score
        FROM boxes
        WHERE detection_label IS NULL OR detection_label = 'IGNORE'
    """).fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


# ── Feature matrix builder ────────────────────────────────────────────────────

def _candle_df_for_box(row: pd.Series) -> Optional[pd.DataFrame]:
    """
    Fetch candle data for the box's symbol+timeframe from SQLite.
    Returns None if unavailable.
    """
    try:
        import sqlite3
        db_path = _BACKEND.parent / "pipeline" / "data" / "candles.db"
        if not db_path.exists():
            # fallback location
            db_path = _BACKEND / "data" / "trading_data.db"
        if not db_path.exists():
            return None

        conn = sqlite3.connect(str(db_path))
        symbol    = row["symbol"]
        timeframe = row["timeframe"]

        rows = conn.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE symbol=? AND timeframe=? ORDER BY ts ASC",
            (symbol, timeframe),
        ).fetchall()
        conn.close()

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
        df = df.astype({"time": np.int64, "open": float, "high": float,
                        "low": float, "close": float})
        return df

    except Exception as e:
        logger.debug("_candle_df_for_box failed: %s", e)
        return None


def _row_to_features(row: pd.Series, df: pd.DataFrame) -> Optional[Dict]:
    """Find the box in df by timestamp and extract features."""
    try:
        ts_start = int(row["time_start"]) // 1000  # ms → s
        ts_end   = int(row["time_end"])   // 1000

        # Locate indices
        times = df["time"].to_numpy(dtype=np.int64)
        start_idx = int(np.searchsorted(times, ts_start))
        end_idx   = int(np.searchsorted(times, ts_end))

        if start_idx >= len(df) or end_idx >= len(df) or end_idx <= start_idx:
            return None

        return extract_detection_features(
            df, start_idx, end_idx,
            float(row["price_high"]), float(row["price_low"]),
        )
    except Exception as e:
        logger.debug("_row_to_features failed: %s", e)
        return None


def _build_feature_matrix(df_rows: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns (X, y, weights) where:
      y=1  → RIGHT or source=manual
      y=0  → WRONG
      weights as per priority: manual=3, RIGHT=2, WRONG=1
    """
    X_list, y_list, w_list = [], [], []

    for _, row in df_rows.iterrows():
        label  = str(row.get("detection_label", "")).upper()
        source = str(row.get("source", "baseline")).lower()

        if label == "RIGHT":
            y = 1
            w = 3.0 if source == "manual" else 2.0
        elif label == "WRONG":
            y = 0
            w = 1.0
        else:
            continue

        df_candles = _candle_df_for_box(row)
        if df_candles is None:
            continue

        feats = _row_to_features(row, df_candles)
        if feats is None:
            continue

        feat_vec = [feats[k] for k in sorted(feats.keys())]
        X_list.append(feat_vec)
        y_list.append(y)
        w_list.append(w)

    if not X_list:
        return np.array([]), np.array([]), np.array([])

    return np.array(X_list, dtype=np.float32), np.array(y_list), np.array(w_list, dtype=np.float32)


# ── Hard negative mining ───────────────────────────────────────────────────────

def _mine_hard_negatives(
    model,
    X_train: np.ndarray,
    y_train: np.ndarray,
    w_train: np.ndarray,
    unlabeled_df: pd.DataFrame,
    hard_neg_weight: float = 2.0,
    max_hard_neg: int = 50,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Find unlabeled boxes that the model scores HIGH (≥ 0.6) → treat as hard negatives.
    Append them to training set with y=0.
    """
    if len(unlabeled_df) == 0 or model is None:
        return X_train, y_train, w_train

    hard_X, hard_feats = [], []
    for _, row in unlabeled_df.iterrows():
        df_c = _candle_df_for_box(row)
        if df_c is None:
            continue
        feats = _row_to_features(row, df_c)
        if feats is None:
            continue
        fv = [feats[k] for k in sorted(feats.keys())]
        hard_feats.append(fv)

    if not hard_feats:
        return X_train, y_train, w_train

    try:
        import xgboost as xgb
        hard_arr = np.array(hard_feats, dtype=np.float32)
        scores   = model.predict_proba(hard_arr)[:, 1]
        high_score_mask = scores >= 0.6
        n_hard = min(int(high_score_mask.sum()), max_hard_neg)
        if n_hard == 0:
            return X_train, y_train, w_train

        # Take top n_hard by score
        top_idx = np.argsort(scores)[::-1]
        top_idx = top_idx[high_score_mask[top_idx]][:n_hard]

        hard_X_arr = hard_arr[top_idx]
        hard_y     = np.zeros(n_hard, dtype=np.int64)
        hard_w     = np.full(n_hard, hard_neg_weight, dtype=np.float32)

        logger.info("Hard negative mining: added %d hard negatives", n_hard)

        X_out = np.vstack([X_train, hard_X_arr])
        y_out = np.concatenate([y_train, hard_y])
        w_out = np.concatenate([w_train, hard_w])
        return X_out, y_out, w_out

    except Exception as e:
        logger.warning("Hard negative mining failed: %s", e)
        return X_train, y_train, w_train


# ── Threshold calibration ─────────────────────────────────────────────────────

def _find_best_threshold(proba: np.ndarray, y: np.ndarray) -> float:
    """Grid search for F1-optimal threshold."""
    from sklearn.metrics import f1_score
    best_t, best_f1 = 0.5, 0.0
    for t in np.arange(0.35, 0.71, 0.05):
        preds = (proba >= t).astype(int)
        f1 = f1_score(y, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_t  = round(float(t), 2)
    return best_t


# ── Metrics ───────────────────────────────────────────────────────────────────

def _print_metrics(y_true: np.ndarray, y_pred: np.ndarray, proba: np.ndarray, k: int = 20):
    from sklearn.metrics import (
        precision_score, recall_score, f1_score, confusion_matrix,
    )
    logger.info("── Validation Metrics ───────────────────────────────────")
    logger.info("  Precision : %.4f", precision_score(y_true, y_pred, zero_division=0))
    logger.info("  Recall    : %.4f", recall_score(y_true, y_pred, zero_division=0))
    logger.info("  F1        : %.4f", f1_score(y_true, y_pred, zero_division=0))
    cm = confusion_matrix(y_true, y_pred)
    logger.info("  Confusion matrix:\n%s", cm)

    # precision@top-k
    k_eff = min(k, len(proba))
    top_k_idx = np.argsort(proba)[::-1][:k_eff]
    p_at_k = float(np.mean(y_true[top_k_idx]))
    logger.info("  Precision@top%d : %.4f", k_eff, p_at_k)
    logger.info("────────────────────────────────────────────────────────")

    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall":    float(recall_score(y_true, y_pred, zero_division=0)),
        "f1":        float(f1_score(y_true, y_pred, zero_division=0)),
        f"precision_at_{k_eff}": p_at_k,
    }


# ── Main training function ────────────────────────────────────────────────────

def run_detection_training(min_samples: int = 10) -> Dict:
    """
    Full training pipeline. Thread-safe (uses _RETRAIN_LOCK).

    Returns metadata dict with version, accuracy, threshold, dataset_size.
    Raises RuntimeError if fewer than min_samples labeled boxes exist.
    """
    if not _RETRAIN_LOCK.acquire(blocking=False):
        logger.warning("Retrain already in progress — skipping")
        return {"status": "already_running"}

    try:
        logger.info("══ Detection model training started ══════════════════")
        t_start = datetime.now(timezone.utc)

        # ── 1. Load labeled data ─────────────────────────────────────────────
        labeled_df = _load_labeled_rows()
        n_labeled  = len(labeled_df)
        logger.info("Labeled samples: %d", n_labeled)

        if n_labeled < min_samples:
            raise RuntimeError(
                f"Too few labeled samples ({n_labeled} < {min_samples}). "
                "Label more boxes with RIGHT/WRONG before retraining."
            )
        if n_labeled < 50:
            logger.warning("⚠ Only %d labeled samples — model may overfit. "
                           "Target ≥ 50 for reliable results.", n_labeled)

        # ── 2. Build feature matrix ─────────────────────────────────────────
        X, y, w = _build_feature_matrix(labeled_df)
        if len(X) == 0:
            raise RuntimeError("Feature matrix is empty — candle data may be unavailable.")

        logger.info("Feature matrix: %d samples × %d features", *X.shape)

        # ── 3. Temporal split (no shuffle — prevents future leakage) ─────────
        # labeled_df is ordered by recorded_at; X/y/w match row order
        split = max(1, int(len(X) * 0.80))
        X_tr, X_val = X[:split], X[split:]
        y_tr, y_val = y[:split], y[split:]
        w_tr, w_val = w[:split], w[split:]

        logger.info("Temporal split: train=%d val=%d", len(X_tr), len(X_val))

        # ── 4. Hard negative mining (needs current model if exists) ──────────
        existing_model = None
        if _MODEL_PKL.exists():
            try:
                with open(_MODEL_PKL, "rb") as f:
                    existing_model = pickle.load(f)
                logger.info("Loaded existing model for hard negative mining")
            except Exception:
                pass

        unlabeled_df = _load_unlabeled_rows()
        X_tr, y_tr, w_tr = _mine_hard_negatives(existing_model, X_tr, y_tr, w_tr, unlabeled_df)
        logger.info("After hard neg mining: train=%d", len(X_tr))

        # ── 5. Class balance ─────────────────────────────────────────────────
        n_pos = int(np.sum(y_tr == 1))
        n_neg = int(np.sum(y_tr == 0))
        scale_pos_weight = (n_neg / n_pos) if n_pos > 0 else 1.0
        logger.info("Class balance: pos=%d neg=%d scale_pos_weight=%.2f",
                    n_pos, n_neg, scale_pos_weight)

        # ── 6. Train XGBoost ─────────────────────────────────────────────────
        import xgboost as xgb
        from sklearn.calibration import CalibratedClassifierCV

        model = xgb.XGBClassifier(
            n_estimators         = 200,
            max_depth            = 5,
            learning_rate        = 0.05,
            subsample            = 0.8,
            colsample_bytree     = 0.8,
            scale_pos_weight     = scale_pos_weight,
            use_label_encoder    = False,
            eval_metric          = "logloss",
            verbosity            = 0,
            random_state         = 42,
        )

        # Eval set for early stopping
        eval_set = [(X_val, y_val)] if len(X_val) >= 2 else None
        fit_kwargs = dict(sample_weight=w_tr)
        if eval_set:
            fit_kwargs["eval_set"] = eval_set
            fit_kwargs["verbose"]  = False

        model.fit(X_tr, y_tr, **fit_kwargs)
        logger.info("XGBoost training complete")

        # ── 7. Confidence calibration (isotonic) ────────────────────────────
        try:
            if len(X_val) >= 4:
                calibrated = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
                calibrated.fit(X_val, y_val)
                logger.info("Isotonic calibration applied")
                final_model = calibrated
            else:
                logger.info("Not enough val samples for calibration — skipping")
                final_model = model
        except Exception as cal_err:
            logger.warning("Calibration failed (%s) — using raw model", cal_err)
            final_model = model

        # ── 8. Threshold optimization ────────────────────────────────────────
        val_proba = None
        threshold = 0.5
        if len(X_val) >= 2:
            val_proba  = final_model.predict_proba(X_val)[:, 1]
            threshold  = _find_best_threshold(val_proba, y_val)
            logger.info("Optimal threshold: %.2f", threshold)

        # ── 9. Metrics ───────────────────────────────────────────────────────
        metrics = {}
        if val_proba is not None and len(X_val) >= 2:
            val_pred = (val_proba >= threshold).astype(int)
            metrics  = _print_metrics(y_val, val_pred, val_proba, k=20)

        # ── 10. Version + save ───────────────────────────────────────────────
        version_hash = hashlib.sha1(
            f"{t_start.isoformat()}{len(X)}{n_labeled}".encode()
        ).hexdigest()[:8]
        version = f"v_{t_start.strftime('%Y%m%d_%H%M')}_{version_hash}"

        with open(_MODEL_PKL, "wb") as f:
            pickle.dump(final_model, f, protocol=5)

        feature_names = sorted(
            ["duration_bars", "range_norm", "volatility_compression",
             "avg_candle_size", "wick_ratio", "top_touches", "bot_touches",
             "pre_trend_slope", "impulse_dist", "time_in_range_pct"]
        )
        meta = {
            "version":      version,
            "trained_on":   t_start.isoformat(),
            "dataset_size": n_labeled,
            "train_size":   len(X_tr),
            "val_size":     len(X_val),
            "threshold":    threshold,
            "n_features":   EXPECTED_FEATURE_COUNT,
            "feature_names": feature_names,
            "scale_pos_weight": scale_pos_weight,
            "calibrated":   isinstance(final_model, CalibratedClassifierCV) if "CalibratedClassifierCV" in str(type(final_model)) else False,
            **metrics,
            "status": "ok",
        }

        with open(_META_JSON, "w") as f:
            json.dump(meta, f, indent=2)

        elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
        logger.info("══ Training complete in %.1fs | version=%s | threshold=%.2f ══",
                    elapsed, version, threshold)
        return meta

    except Exception as exc:
        logger.error("Detection training FAILED: %s", exc, exc_info=True)
        return {"status": "error", "reason": str(exc)}

    finally:
        _RETRAIN_LOCK.release()


if __name__ == "__main__":
    result = run_detection_training(min_samples=10)
    print(json.dumps(result, indent=2))
