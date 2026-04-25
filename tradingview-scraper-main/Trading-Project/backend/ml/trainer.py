"""
ml/trainer.py — LightGBM training pipeline with concurrency safety.

Trigger: every 500 unconsumed labels globally.
Gate: Precision_good >= 0.60 AND support_good >= 30.
On success: promote model, reload scorer, mark labels consumed.
On failure: keep old model, do NOT consume labels.
"""

import os
import threading
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

from ml import db as ml_db
from ml.features import FEATURE_VERSION

logger = logging.getLogger(__name__)

INITIAL_RETRAIN_N = 50
SUBSEQUENT_RETRAIN_N = 50

def get_retrain_threshold() -> int:
    try:
        total = ml_db.count_all_labels()
        if total < INITIAL_RETRAIN_N:
            return INITIAL_RETRAIN_N
        return SUBSEQUENT_RETRAIN_N
    except Exception:
        return SUBSEQUENT_RETRAIN_N

# ── Globals ───────────────────────────────────────────────────────────────────

# very_good = strong positive, good = positive, bad = negative, very_bad = strong negative
CLASS_MAP = {"very_good": 0, "good": 1, "bad": 2, "very_bad": 3}
CLASS_WEIGHTS = {0: 3.0, 1: 1.0, 2: 1.0, 3: 2.0}

_train_lock = threading.Lock()

# Models save directory (relative to this file)
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "models")

# ── Training Real-Time State ──────────────────────────────────────────────────

TRAINING_STATE = {
    "is_training": False,
    "iteration": 0,
    "max_iterations": 1000,
    "val_logloss": 0.0,
    "logs": []
}

def _log_msg(msg: str):
    logger.info(msg)
    TRAINING_STATE["logs"].append(msg)
    # Keep last 100 logs
    if len(TRAINING_STATE["logs"]) > 100:
        TRAINING_STATE["logs"].pop(0)

def lgb_progress_callback(env):
    """LightGBM custom callback to feed real-time iteration metrics."""
    TRAINING_STATE["iteration"] = env.iteration
    # Attempt to extract metric (multi_logloss)
    if env.evaluation_result_list:
        try:
            val_loss = env.evaluation_result_list[0][2]
            TRAINING_STATE["val_logloss"] = float(val_loss)
        except Exception:
            pass



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
    # Forced GPU execution
    # Warning: If OpenCL/CUDA drivers are not installed, training will crash.
    return "gpu"


# ── Trigger ───────────────────────────────────────────────────────────────────

def maybe_trigger_retrain() -> None:
    """
    Non-blocking. Called after every new label.
    Uses lock.locked() to avoid duplicate jobs.
    """
    threshold = get_retrain_threshold()
    if ml_db.count_unconsumed() < threshold:
        return
    if _train_lock.locked():
        logger.info("[trainer] Training already in progress — skip duplicate trigger")
        return

    def train_job():
        with _train_lock:
            try:
                TRAINING_STATE["logs"] = []
                TRAINING_STATE["is_training"] = True
                _log_msg("[trainer] Starting async training job...")
                _run_training()
            except Exception as exc:
                _log_msg(f"[trainer] Error: {exc}")
                logger.error("[trainer] Training failed: %s", exc, exc_info=True)
            finally:
                TRAINING_STATE["is_training"] = False

    t = threading.Thread(target=train_job, daemon=True, name="ml-trainer")
    t.start()
    logger.info("[trainer] Training thread started")


# ── Main training pipeline ────────────────────────────────────────────────────

def _run_training(force: bool = False) -> None:
    """
    Full training pipeline. Runs inside _train_lock.
    If force=True, bypass the 500 label minimum check.
    """
    import lightgbm as lgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
    import joblib

    TRAINING_STATE["is_training"] = True
    TRAINING_STATE["iteration"] = 0
    TRAINING_STATE["val_logloss"] = 0.0

    _log_msg("[trainer] === Starting training run ===")

    # ── 1. Load unconsumed labels ─────────────────────────────────────────────
    raw_labels = ml_db.get_unconsumed_labels()
    threshold = get_retrain_threshold()
    if not force and len(raw_labels) < threshold:
        _log_msg(f"[trainer] Unconsumed count {len(raw_labels)} < {threshold} — abort")
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

    if not force and len(valid_rows) < 100:
        _log_msg(f"[trainer] Not enough valid rows ({len(valid_rows)}) — abort (need 100)")
        return

    # ── 3. Deduplicate: keep LATEST label per box ─────────────────────────────
    latest: dict = {}
    for r, vec in valid_rows:
        bid = r["box_id"]
        if bid not in latest or r["created_at"] > latest[bid][0]["created_at"]:
            latest[bid] = (r, vec)

    rows_deduped = list(latest.values())
    _log_msg(f"[trainer] Unique boxes after dedup: {len(rows_deduped)}")

    # ── 4. Build X, y, sample weights ────────────────────────────────────────
    X = np.array([vec for _, vec in rows_deduped], dtype=np.float32)
    y = np.array([CLASS_MAP[r["label"]] for r, _ in rows_deduped], dtype=np.int32)
    w = np.array([CLASS_WEIGHTS[yi] for yi in y], dtype=np.float32)

    # Check class distribution
    unique, counts = np.unique(y, return_counts=True)
    dist = dict(zip(unique.tolist(), counts.tolist()))
    _log_msg(f"[trainer] Classes: {dist}")

    # Need at least some "good" samples for meaningful gate check
    if dist.get(0, 0) + dist.get(1, 0) < 5:
        logger.warning("[trainer] Too few 'good' samples (%d) — abort", dist.get(0, 0) + dist.get(1, 0))
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
        "num_class": 4,
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

    TRAINING_STATE["max_iterations"] = lgb_params["n_estimators"]

    lgbm_clf.fit(
        X_train, y_train,
        sample_weight=w_train,
        eval_set=[(X_val, y_val)],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb_progress_callback
        ],
    )

    # ── 7. Calibrate ─────────────────────────────────────────────────────────
    _log_msg("[trainer] Calibrating model...")
    try:
        # Cross-validation calibration needs enough samples per class
        calibrated = CalibratedClassifierCV(lgbm_clf, cv=min(5, len(X_train)), method="sigmoid")
        calibrated.fit(X_train, y_train, sample_weight=w_train)
    except Exception as e:
        _log_msg(f"[trainer] CV calibration failed ({e}). Falling back to prefit.")
        calibrated = CalibratedClassifierCV(lgbm_clf, cv="prefit", method="sigmoid")
        calibrated.fit(X_val, y_val)

    # ── 8. Evaluate ──────────────────────────────────────────────────────────
    y_pred = calibrated.predict(X_val)
    y_proba = calibrated.predict_proba(X_val)

    report = classification_report(
        y_val, y_pred,
        target_names=["very_good", "good", "bad", "very_bad"],
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_val, y_pred)

    # Define target classes that represent "success"
    precision_vg = report.get("very_good", {}).get("precision", 0)
    support_vg   = report.get("very_good", {}).get("support", 0)
    
    precision_g  = report.get("good", {}).get("precision", 0)
    support_g    = report.get("good", {}).get("support", 0)

    # Combined check logic (needs enough support across both positive classes)
    total_good_support = support_vg + support_g
    avg_good_precision = ((precision_vg * support_vg) + (precision_g * support_g)) / max(1, total_good_support)

    _log_msg(f"[trainer] Evaluation:")
    _log_msg(f"  -> VG: P={precision_vg:.2f} (supp={support_vg})")
    _log_msg(f"  ->  G: P={precision_g:.2f} (supp={support_g})")
    
    gate_passed = avg_good_precision >= 0.60 and total_good_support >= 30

    _log_msg(f"[trainer] Gate check: Avg Good P={avg_good_precision:.2f} (need 0.60), Support={total_good_support} (need 30)")
    
    if not gate_passed:
        _log_msg("[trainer] Gate FAILED — NOT promoted")
        return

    # Error analysis for class 'good' (0)
    fps_mask = (y_val != 0) & (y_val != 1) & ((y_pred == 0) | (y_pred == 1))
    fps = np.where(fps_mask)[0]
    fns = np.where((y_pred != 0) & (y_pred != 1) & ((y_val == 0) | (y_val == 1)))[0]
    _log_msg(f"[trainer] Error Analysis (Good Class): FP={len(fps)} | FN={len(fns)}")
    if len(fps) > 0:
        _log_msg(f"[trainer] FP: Model predicted VERY_GOOD/GOOD on {len(fps)} BAD/VERY_BAD samples")
    if len(fns) > 0:
        _log_msg(f"[trainer] FN: Model missed {len(fns)} true GOOD samples")

    # ── 9. Export Data & Consume Labels ──────────────────────────────────────
    import csv
    from datetime import datetime

    exports_dir = os.path.join(os.path.dirname(__file__), "..", "data", "ml_exports")
    os.makedirs(exports_dir, exist_ok=True)
    export_path = os.path.join(exports_dir, f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    
    try:
        with open(export_path, "w", newline="") as f:
            if rows_deduped:
                # Write label row data + features
                writer = csv.writer(f)
                header = ["id", "box_id", "label", "created_at"]
                if len(rows_deduped) > 0:
                    header.extend([f"f_{i}" for i in range(len(rows_deduped[0][1]))])
                writer.writerow(header)
                for r, vec in rows_deduped:
                    row = [r["id"], r["box_id"], r["label"], r.get("created_at", "")]
                    row.extend(vec.tolist())
                    writer.writerow(row)
        _log_msg(f"[trainer] Exported training data to {export_path}")
    except Exception as e:
        _log_msg(f"[trainer] Failed exporting data: {e}")

    # Consume labels unconditionally so the counter resets
    label_ids = [r["id"] for r, _ in rows_deduped]
    ml_db.mark_consumed(label_ids)
    _log_msg(f"[trainer] Marked {len(label_ids)} labels as consumed (Counter reset)")

    # ── 9. Save & Promote ────────────────────────────────────────────────────
    model_version = int(time.time())
    model_meta = {
        "version": model_version,
        "feature_version": FEATURE_VERSION,
        "classes": ["very_good", "good", "bad", "very_bad"],
        "precision_good": float(avg_good_precision),
        "recall_good": float(report.get("good", {}).get("recall", 0.0)),
        "f1_good": float(report.get("good", {}).get("f1-score", 0.0)),
        "support_good": int(total_good_support),
        "trained_on_samples": len(rows_deduped),
        "created_at_iso": datetime.utcnow().isoformat() + "Z"
    }

    _log_msg(f"[trainer] Saving model v{model_version}...")
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    model_path = model_dir / f"lightgbm_v{model_version}.pkl"

    joblib.dump({
        "model": calibrated,
        "meta": model_meta
    }, model_path)

    ml_db.save_model_metadata(
        version_id=model_version,
        precision_good=float(avg_good_precision),
        recall_good=float(report.get("good", {}).get("recall", 0.0)),
        f1_good=float(report.get("good", {}).get("f1-score", 0.0)),
        support_good=int(total_good_support),
        samples_count=len(rows_deduped),
        feature_ver=FEATURE_VERSION,
        path=str(model_path)
    )

    from ml import scorer
    scorer.load_model()

    _log_msg(f"[trainer] === Training complete: {model_version} promoted ===")
