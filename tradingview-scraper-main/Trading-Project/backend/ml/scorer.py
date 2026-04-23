"""
ml/scorer.py — Model inference layer.

Loads latest promoted model from DB at startup.
Supports single-box and batch scoring.
Always returns the inference contract dict.
Falls back to FALLBACK on missing model or any error.
"""

import logging
import threading
from typing import Optional

import numpy as np

from ml import db as ml_db

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────
_model = None           # calibrated LGBMClassifier
_model_version: Optional[str] = None
_model_lock = threading.RLock()

# ── Fallback response ─────────────────────────────────────────────────────────
FALLBACK = {
    "probabilities": {"very_good": 0.25, "good": 0.25, "bad": 0.25, "very_bad": 0.25},
    "confidence": 0.01,
    "model_version": None,
    "is_fallback": True,
}


def _confidence(proba: np.ndarray) -> float:
    """confidence = max(p) - second_max(p)"""
    sorted_p = np.sort(proba)[::-1]
    if len(sorted_p) < 2:
        return 0.0
    return float(sorted_p[0] - sorted_p[1])


def load_model() -> None:
    """
    Load the currently promoted model from DB.
    Called at startup and after each successful retrain.
    Thread-safe.
    """
    global _model, _model_version

    checkpoint = ml_db.get_active_model()
    if not checkpoint:
        logger.info("[scorer] No promoted model found — running in cold start mode")
        return

    pkl_path = checkpoint["pkl_path"]
    version = checkpoint["version"]

    try:
        import joblib
        with _model_lock:
            _model = joblib.load(pkl_path)
            _model_version = version
        logger.info("[scorer] Loaded model %s from %s", version, pkl_path)
    except Exception as exc:
        logger.error("[scorer] Failed to load model %s: %s", pkl_path, exc)
        with _model_lock:
            _model = None
            _model_version = None


def reload_model() -> None:
    """Hot-swap model after promotion. Alias for load_model."""
    load_model()


def score_box(box_id: str) -> dict:
    """
    Score a single box by its box_id.
    Returns inference contract dict.
    Falls back to FALLBACK on missing features or model.
    """
    with _model_lock:
        m = _model
        mv = _model_version

    if m is None:
        return FALLBACK

    vec = ml_db.get_feature_vec(box_id)
    if vec is None:
        return FALLBACK

    try:
        X = np.array([vec], dtype=np.float32)
        proba = m.predict_proba(X)[0]
        p = {
            "very_good": float(proba[0]),
            "good":      float(proba[1]),
            "bad":       float(proba[2]),
            "very_bad":  float(proba[3]),
        }
        return {
            "probabilities": p,
            "confidence":    _confidence(proba),
            "model_version": mv,
            "is_fallback":   False,
        }
    except Exception as exc:
        logger.error("[scorer] Inference failed for %s: %s", box_id, exc)
        return FALLBACK


def batch_score(box_ids: list) -> dict:
    """
    Score multiple boxes in a single predict_proba call.
    Returns {box_id: inference_contract_dict}.
    Boxes with no feature vector get FALLBACK.
    """
    result = {bid: FALLBACK for bid in box_ids}

    with _model_lock:
        m = _model
        mv = _model_version

    if m is None or not box_ids:
        return result

    # Collect vecs for boxes that have features
    has_feat = {}
    for bid in box_ids:
        vec = ml_db.get_feature_vec(bid)
        if vec is not None:
            has_feat[bid] = vec

    if not has_feat:
        return result

    try:
        ids_ordered = list(has_feat.keys())
        X = np.array([has_feat[bid] for bid in ids_ordered], dtype=np.float32)
        probas = m.predict_proba(X)  # shape (N, 3)

        for i, bid in enumerate(ids_ordered):
            proba = probas[i]
            p = {
                "very_good": float(proba[0]),
                "good":      float(proba[1]),
                "bad":       float(proba[2]),
                "very_bad":  float(proba[3]),
            }
            result[bid] = {
                "probabilities": p,
                "confidence":    _confidence(proba),
                "model_version": mv,
                "is_fallback":   False,
            }
    except Exception as exc:
        logger.error("[scorer] Batch inference failed: %s", exc)

    return result


def get_model_version() -> Optional[str]:
    with _model_lock:
        return _model_version


def is_model_ready() -> bool:
    with _model_lock:
        return _model is not None
