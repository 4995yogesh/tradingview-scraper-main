"""
detection_scorer.py — Inference for the detection model.

Loads detection_model.pkl and scores candidate boxes.
Degrades gracefully if model is absent — returns None scores.
"""

import logging
import pickle
import json
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

_HERE      = Path(__file__).resolve().parent
_MODEL_PKL = _HERE / "detection_model.pkl"
_META_JSON = _HERE / "detection_model_meta.json"

# Feature order must match detection_train.py (alphabetical sort of feature dict)
_FEATURE_NAMES = sorted([
    "duration_bars", "range_norm", "volatility_compression",
    "avg_candle_size", "wick_ratio", "top_touches", "bot_touches",
    "pre_trend_slope", "impulse_dist", "time_in_range_pct",
])


class DetectionScorer:
    """
    Thread-safe inference wrapper around detection_model.pkl.

    Usage:
        scorer = DetectionScorer()
        candidates = generate_candidates(df)
        scored = scorer.score_candidates(df, candidates)
        # Each candidate now has detection_score (float) and detection_score_calibrated (float)
    """

    def __init__(self):
        self._model    = None
        self._threshold = 0.5
        self._version   = "none"
        self._ready     = False
        self._load()

    def _load(self):
        try:
            if not _MODEL_PKL.exists():
                logger.info("DetectionScorer: no model found at %s — will degrade gracefully", _MODEL_PKL)
                return

            with open(_MODEL_PKL, "rb") as f:
                self._model = pickle.load(f)

            if _META_JSON.exists():
                with open(_META_JSON) as f:
                    meta = json.load(f)
                self._threshold = float(meta.get("threshold", 0.5))
                self._version   = str(meta.get("version", "unknown"))

            self._ready = True
            logger.info("DetectionScorer: loaded model version=%s threshold=%.2f",
                        self._version, self._threshold)

        except Exception as e:
            logger.warning("DetectionScorer: load failed — %s", e)
            self._model = None
            self._ready = False

    def reload(self):
        """Reload model from disk (call after retraining)."""
        self._load()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def version(self) -> str:
        return self._version

    @property
    def threshold(self) -> float:
        return self._threshold

    def meta(self) -> Dict:
        base = {
            "ready":    self._ready,
            "version":  self._version,
            "threshold": self._threshold,
            "feature_names": _FEATURE_NAMES,
        }
        if _META_JSON.exists():
            try:
                with open(_META_JSON) as f:
                    base.update(json.load(f))
            except Exception:
                pass
        return base

    def score_candidates(
        self,
        df,                        # pd.DataFrame with OHLC
        candidates: List[Dict],
        extract_fn=None,           # inject detection_features.extract_detection_features
    ) -> List[Dict]:
        """
        Add detection_score and detection_label to each candidate dict.
        Returns same list (mutated in place) — always returns without crashing.

        Parameters
        ----------
        df          : full candle DataFrame
        candidates  : list of dicts from generate_candidates()
        extract_fn  : optional injection for testing; defaults to import
        """
        if not candidates:
            return candidates

        # Fallback: no model available
        if not self._ready or self._model is None:
            for c in candidates:
                c["detection_score"]  = None
                c["detection_label"]  = "unscored"
                c["model_version"]    = "none"
            return candidates

        if extract_fn is None:
            from detection_features import extract_detection_features as extract_fn

        X_list  = []
        valid_idx = []  # which candidates got features

        for i, cand in enumerate(candidates):
            try:
                feats = extract_fn(
                    df,
                    cand["start"], cand["end"],
                    cand["price_high"], cand["price_low"],
                )
                if feats is None:
                    continue
                feat_vec = [feats[k] for k in _FEATURE_NAMES]
                # Replace any non-finite value with 0
                feat_vec = [v if np.isfinite(v) else 0.0 for v in feat_vec]
                X_list.append(feat_vec)
                valid_idx.append(i)
            except Exception as e:
                logger.debug("score_candidates: feature extraction failed idx=%d: %s", i, e)

        # Mark unscored first
        for c in candidates:
            c["detection_score"] = None
            c["detection_label"] = "unscored"
            c["model_version"]   = self._version

        if not X_list:
            return candidates

        try:
            X = np.array(X_list, dtype=np.float32)
            proba = self._model.predict_proba(X)[:, 1]

            for list_i, cand_i in enumerate(valid_idx):
                score = float(proba[list_i])
                candidates[cand_i]["detection_score"] = round(score, 4)
                candidates[cand_i]["detection_label"] = (
                    "valid"   if score >= self._threshold else
                    "uncertain" if score >= 0.45 and score < 0.55 else
                    "invalid"
                )

        except Exception as e:
            logger.warning("DetectionScorer.score_candidates predict failed: %s", e)
            # Fallback: return candidates with score=None (already set)

        return candidates

    def score_single(self, feats: Dict) -> Optional[float]:
        """Score a single pre-extracted feature dict. Returns None on failure."""
        if not self._ready or self._model is None:
            return None
        try:
            feat_vec = [[feats.get(k, 0.0) for k in _FEATURE_NAMES]]
            feat_vec = [[v if np.isfinite(v) else 0.0 for v in feat_vec[0]]]
            proba = self._model.predict_proba(np.array(feat_vec, dtype=np.float32))
            return float(proba[0, 1])
        except Exception as e:
            logger.warning("DetectionScorer.score_single failed: %s", e)
            return None


# ── Module-level singleton (for server.py to import) ──────────────────────────
_detection_scorer: Optional[DetectionScorer] = None


def get_detection_scorer() -> DetectionScorer:
    """Lazy singleton initializer."""
    global _detection_scorer
    if _detection_scorer is None:
        _detection_scorer = DetectionScorer()
    return _detection_scorer
