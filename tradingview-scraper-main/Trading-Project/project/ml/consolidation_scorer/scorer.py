"""
scorer.py v2 — Production inference for consolidation box quality scoring.

Changes from v1:
  - Uses optimal_threshold from model.pkl (calibrated on validation set)
  - Uses col_medians from model.pkl (consistent imputation between train/infer)
  - Exposes scorer.threshold for frontend thresholding
  - Color gradient: red → amber → green using score quartiles
"""

import pickle
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

from ml.consolidation_scorer.features import build_feature_matrix

logger    = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parent / "model.pkl"


class ConsolidationScorer:
    """
    Thread-safe inference scorer. Loads once at startup; predict() is stateless.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self._model        = None
        self._feature_cols = None
        self._col_medians  = {}
        self._meta         = {}
        self.threshold     = 0.3   # fallback default
        self._load(model_path or MODEL_PATH)

    def _load(self, path: Path):
        if not path.exists():
            logger.warning("No model at %s — scorer disabled", path)
            return
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._model        = data["model"]
        self._feature_cols = data["feature_cols"]
        self._col_medians  = data.get("col_medians", {})
        self.threshold     = float(data.get("optimal_threshold", 0.3))
        self._meta         = {k: v for k, v in data.items()
                              if k not in ("model", "feature_cols", "col_medians")}
        logger.info(
            "ConsolidationScorer v2 | %s [%s] | train=%d | r=%.3f | θ=%.3f",
            self._meta.get("symbol", "?"), self._meta.get("timeframe", "?"),
            self._meta.get("train_rows", 0),
            self._meta.get("pearson_r", 0.0),
            self.threshold,
        )

    @property
    def ready(self) -> bool:
        return self._model is not None

    def score(
        self,
        df: pd.DataFrame,
        boxes: pd.DataFrame,
        threshold: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Score all boxes and attach quality + quality_color columns.

        Parameters
        ----------
        df        : OHLC DataFrame used for detection.
        boxes     : Boxes from consolidation_boxes() (start, end, top, bottom).
        threshold : Override for filtering threshold (default: calibrated value).

        Returns
        -------
        boxes copy with columns: quality [0,1], quality_color (hex).
        """
        use_thresh = threshold if threshold is not None else self.threshold

        if not self.ready or boxes.empty:
            out = boxes.copy()
            out["quality"]       = 0.5
            out["quality_color"] = "#FFB86C"
            return out

        feat_df = build_feature_matrix(df, boxes)
        if feat_df.empty:
            out = boxes.copy()
            out["quality"]       = 0.5
            out["quality_color"] = "#FFB86C"
            return out

        # Align and sanitise features
        use_cols = self._feature_cols
        for col in use_cols:
            if col not in feat_df.columns:
                feat_df[col] = self._col_medians.get(col, 0.0)

        X = feat_df[use_cols].astype(np.float32)
        # Use training column medians for imputation (consistent with training)
        for col in use_cols:
            fill_val = self._col_medians.get(col, 0.0)
            X[col] = X[col].replace([np.inf, -np.inf], np.nan).fillna(fill_val)

        preds = np.clip(self._model.predict(X), 0.0, 1.0)

        scored = boxes.copy()
        scored["quality"] = np.nan
        for i, box_idx in enumerate(feat_df.index):
            if i < len(preds):
                scored.loc[box_idx, "quality"] = float(preds[i])

        scored["quality"]       = scored["quality"].fillna(0.5)
        scored["quality_color"] = scored["quality"].apply(_quality_to_color)

        # Apply threshold filter
        if use_thresh > 0:
            scored = scored[scored["quality"] >= use_thresh].copy()

        return scored

    def meta(self) -> dict:
        return {**self._meta, "threshold": self.threshold, "ready": self.ready}


# ─────────────────────────────────────────────────────────────────────────────
# Color mapping: red → amber → green
# ─────────────────────────────────────────────────────────────────────────────

def _quality_to_color(q: float) -> str:
    """
    0.0 → #EF5350 (red)
    0.5 → #FFB86C (amber)
    1.0 → #26A69A (teal-green)
    """
    q = float(np.clip(q, 0.0, 1.0))
    if q < 0.5:
        t = q / 0.5                                  # 0→1 in red→amber
        r = int(239 + t * (255 - 239))
        g = int(83  + t * (184 - 83))
        b = int(80  + t * (108 - 80))
    else:
        t = (q - 0.5) / 0.5                          # 0→1 in amber→green
        r = int(255 + t * (38  - 255))
        g = int(184 + t * (166 - 184))
        b = int(108 + t * (154 - 108))
    return f"#{r:02X}{g:02X}{b:02X}"


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────
consolidation_scorer = ConsolidationScorer()
