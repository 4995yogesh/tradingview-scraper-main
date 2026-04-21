"""
ml/trainer.py — LightGBM training pipeline with concurrency safety.

Trigger: every 100 unconsumed labels globally.
Gate: Precision_good >= 0.60 AND support_good >= 30.
On success: promote model, reload scorer, mark labels consumed.
On failure: keep old model, do NOT consume labels.
"""

import os
import threading
import logging
import time
from typing import Optional

import numpy as np

from ml import db as ml_db
from ml.features import FEATURE_VERSION

logger = logging.getLogger(__name__)

RETRAIN_EVERY_N = 100
CLASS_MAP = {"good": 0, "bad": 1, "neutral": 2}
CLASS_WEIGHTS = {0: 1.0, 1: 1.0, 2: 0.4}

_train_lock = threading.Lock()

# Models save directory (relative to this file)
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "models")


# ── GPU detection ─────────────────────────────────────────────────────────────

def has_gpu() -> bool:
    """LightGBM-native GPU probe. Silently falls back to False."""
    try:
        import lightgbm as lgb
        test_data = lgb.Dataset([[0.0, 1.0]], label=[0])
        test_data.construct()
        lgb.train(
            {
                "device": "gpu",
                "objective": "binary",
                "verbose": -1,
                "num_iterations": 1,
            },
            test_data,
            valid_sets=[test_data],
            callbacks=[lgb.early_stopping(1, verbose=False)],
        )
        logger.info("[trainer] GPU detected — will use device=gpu")
        return True
    except Exception as e:
        logger.info("[trainer] GPU not available (%s) — using CPU", str(e)[:60])
        return False


_USE_GPU: Optional[bool] = None  # cached after first call

def _device() -> str:
    global _USE_GPU
    if _USE_GPU is None:
        _USE_GPU = has_gpu()
    return "gpu" if _USE_GPU else "cpu"


# ── Trigger ───────────────────────────────────────────────────────────────────

def maybe_trigger_retrain() -> None:
    """
    Non-blocking. Called after every new label.
    Uses lock.locked() to avoid duplicate jobs.
    """
    if ml_db.count_unconsumed() < RETRAIN_EVERY_N:
        return
    if _train_lock.locked():
        logger.info("[trainer] Training already in progress — skip duplicate trigger")
        return

    def train_job():
        with _train_lock:
            try:
                _run_training()
            except Exception as exc:
                logger.error("[trainer] Training failed: %s", exc, exc_info=True)

    t = threading.Thread(target=train_job, daemon=True, name="ml-trainer")
    t.start()
    logger.info("[trainer] Training thread started")


# ── Main training pipeline ────────────────────────────────────────────────────

def _run_training() -> None:
    """
    Full training pipeline. Runs inside _train_lock.
    """
    import lightgbm as lgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
    import joblib

    logger.info("[trainer] === Starting training run ===")

    # ── 1. Load unconsumed labels ─────────────────────────────────────────────
    raw_labels = ml_db.get_unconsumed_labels()
    if len(raw_labels) < RETRAIN_EVERY_N:
        logger.info("[trainer] Unconsumed count %d < %d — abort", len(raw_labels), RETRAIN_EVERY_N)
        return

    # ── 2. Join with feature store, skip mismatches ───────────────────────────
    valid_rows = []
    skipped = 0
    for r in raw_labels:
        vec = ml_db.get_feature_vec(r["box_id"])
        if vec is None:
            logger.debug("[trainer] No features for %s — skip", r["box_id"])
            skipped += 1
            continue
        if r.get("feature_ver", "v1") != FEATURE_VERSION:
            logger.warning("[trainer] Feature ver mismatch for %s — skip", r["box_id"])
            skipped += 1
            continue
        valid_rows.append((r, vec))

    logger.info("[trainer] Valid rows: %d / %d (skipped %d)",
                len(valid_rows), len(raw_labels), skipped)

    if len(valid_rows) < RETRAIN_EVERY_N:
        logger.warning("[trainer] Not enough valid rows (%d) — abort", len(valid_rows))
        return

    # ── 3. Deduplicate: keep LATEST label per box ─────────────────────────────
    latest: dict = {}
    for r, vec in valid_rows:
        bid = r["box_id"]
        if bid not in latest or r["created_at"] > latest[bid][0]["created_at"]:
            latest[bid] = (r, vec)

    rows_deduped = list(latest.values())
    logger.info("[trainer] Unique boxes after dedup: %d", len(rows_deduped))

    # ── 4. Build X, y, sample weights ────────────────────────────────────────
    X = np.array([vec for _, vec in rows_deduped], dtype=np.float32)
    y = np.array([CLASS_MAP[r["label"]] for r, _ in rows_deduped], dtype=np.int32)
    w = np.array([CLASS_WEIGHTS[yi] for yi in y], dtype=np.float32)

    # Check class distribution
    unique, counts = np.unique(y, return_counts=True)
    dist = dict(zip(unique.tolist(), counts.tolist()))
    logger.info("[trainer] Class distribution: %s", dist)

    # Need at least some "good" samples for meaningful gate check
    if dist.get(0, 0) < 5:
        logger.warning("[trainer] Too few 'good' samples (%d) — abort", dist.get(0, 0))
        return

    # ── 5. Stratified train/val split ────────────────────────────────────────
    try:
        X_train, X_val, y_train, y_val, w_train, _ = train_test_split(
            X, y, w, test_size=0.2, stratify=y, random_state=42
        )
    except ValueError:
        # Stratify fails if class has < 2 samples — fall back to random split
        logger.warning("[trainer] Stratify failed — using non-stratified split")
        X_train, X_val, y_train, y_val, w_train, _ = train_test_split(
            X, y, w, test_size=0.2, random_state=42
        )

    # ── 6. Train LightGBM ────────────────────────────────────────────────────
    device = _device()
    lgb_params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "n_estimators": 1000,
        "device": device,
        "verbose": -1,
        "random_state": 42,
    }

    # LightGBM sklearn API
    from lightgbm import LGBMClassifier
    lgbm_clf = LGBMClassifier(**lgb_params)

    lgbm_clf.fit(
        X_train, y_train,
        sample_weight=w_train,
        eval_set=[(X_val, y_val)],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=-1),
        ],
    )

    # ── 7. Calibrate ─────────────────────────────────────────────────────────
    logger.info("[trainer] Calibrating model...")
    calibrated = CalibratedClassifierCV(lgbm_clf, cv=5, method="sigmoid")
    calibrated.fit(X_train, y_train, sample_weight=w_train)

    # ── 8. Evaluate ──────────────────────────────────────────────────────────
    y_pred = calibrated.predict(X_val)
    y_proba = calibrated.predict_proba(X_val)

    report = classification_report(
        y_val, y_pred,
        target_names=["good", "bad", "neutral"],
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_val, y_pred)

    precision_good = report.get("good", {}).get("precision", 0.0)
    recall_good    = report.get("good", {}).get("recall", 0.0)
    f1_good        = report.get("good", {}).get("f1-score", 0.0)
    support_good   = int(report.get("good", {}).get("support", 0))

    logger.info("[trainer] === Evaluation Results ===")
    logger.info("[trainer] Confusion Matrix:\n%s", cm)
    logger.info("[trainer] Classification Report:\n%s",
                classification_report(y_val, y_pred,
                                     target_names=["good", "bad", "neutral"],
                                     zero_division=0))
    logger.info("[trainer] Precision_good=%.3f | Recall_good=%.3f | Support_good=%d",
                precision_good, recall_good, support_good)

    # ── 9. Promotion gate ────────────────────────────────────────────────────
    passed = precision_good >= 0.60 and support_good >= 30

    if not passed:
        logger.warning(
            "[trainer] Gate FAILED: Precision_good=%.3f (need 0.60), "
            "support_good=%d (need 30) — model NOT promoted",
            precision_good, support_good,
        )
        return  # Labels stay unconsumed

    # ── 10. Promote ──────────────────────────────────────────────────────────
    version = ml_db.next_model_version()
    os.makedirs(_MODELS_DIR, exist_ok=True)
    pkl_path = os.path.join(_MODELS_DIR, f"model_{version.replace('.', '_')}.pkl")

    joblib.dump(calibrated, pkl_path)
    logger.info("[trainer] Saved model → %s", pkl_path)

    metrics = {
        "label_count":    len(rows_deduped),
        "precision_good": precision_good,
        "recall_good":    recall_good,
        "f1_good":        f1_good,
        "support_good":   support_good,
    }
    ml_db.save_checkpoint(version, metrics, pkl_path, FEATURE_VERSION)
    ml_db.promote_checkpoint(version)

    # Reload model in scorer (hot swap — no restart needed)
    from ml import scorer
    scorer.load_model()
    logger.info("[trainer] Scorer reloaded with model %s", version)

    # Mark labels consumed
    label_ids = [r["id"] for r, _ in rows_deduped]
    ml_db.mark_consumed(label_ids)
    logger.info("[trainer] Marked %d labels as consumed", len(label_ids))

    logger.info("[trainer] === Training complete: %s promoted ===", version)
