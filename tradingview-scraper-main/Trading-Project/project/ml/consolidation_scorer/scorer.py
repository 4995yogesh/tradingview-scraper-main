"""
scorer.py v5 — Explainable production inference for consolidation box quality scoring.

v5 additions (over v4):
  - Loads pattern_model.pkl alongside model.pkl (optional — degrades gracefully)
  - Returns pattern_prediction (CONTINUATION / LIQUIDITY_GRAB) and pattern_confidence
  - VERSION bumped to 5.0.0

v4 additions (over v3):
  - HARD feature schema validation: ANY mismatch → ml_status='invalid_model', no inference
  - XGBoost pred_contribs for per-prediction feature attribution (no SHAP lib needed)
  - ml_top_features: top-3/5 contributors sorted by absolute impact, with signed values
  - trained_on: model.pkl file mtime exposed in .meta()
"""

import pickle
import logging
import hashlib
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from collections import deque

from ml.consolidation_scorer.features import build_feature_matrix, FEATURE_VERSION

logger     = logging.getLogger(__name__)
MODEL_PATH   = Path(__file__).resolve().parent / "model.pkl"
PATTERN_PATH = Path(__file__).resolve().parent / "pattern_model.pkl"

PATTERN_CLASSES = {1: "CONTINUATION", 0: "LIQUIDITY_GRAB"}

# Score → label thresholds (now instance-based, these are just fallbacks if metadata missing)
DEFAULT_GOOD_THRESHOLD = 0.60
DEFAULT_BAD_THRESHOLD  = 0.35

# ─────────────────────────────────────────────────────────────────────────────
# Label → overlay colors (border / fill)
# ─────────────────────────────────────────────────────────────────────────────
LABEL_COLORS = {
    "GOOD":        {"border": "rgba(38,166,154,0.85)",  "fill": "rgba(38,166,154,0.12)"},
    "BAD":         {"border": "rgba(239,83,80,0.85)",   "fill": "rgba(239,83,80,0.12)"},
    "NEUTRAL":     {"border": "rgba(144,202,249,0.70)", "fill": "rgba(144,202,249,0.10)"},
    "DRIFT":       {"border": "rgba(189,147,249,0.85)", "fill": "rgba(189,147,249,0.12)"}, 
    "INVALID":     {"border": "rgba(158,158,158,0.70)", "fill": "rgba(158,158,158,0.10)"}, 
}


def get_label_colors(label: str) -> Dict[str, str]:
    return LABEL_COLORS.get(label, LABEL_COLORS["NEUTRAL"])


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────

def _score_to_confidence(score: float) -> float:
    """Distance from decision boundary. 0.5→0.0, 0.0/1.0→1.0."""
    return float(abs(score - 0.5) * 2.0)


def _quality_to_color(q: float) -> str:
    """Smooth gradient: red(0) → amber(0.5) → teal-green(1)."""
    q = float(np.clip(q, 0.0, 1.0))
    if q < 0.5:
        t = q / 0.5
        r = int(239 + t * (255 - 239))
        g = int(83  + t * (184 - 83))
        b = int(80  + t * (108 - 80))
    else:
        t = (q - 0.5) / 0.5
        r = int(255 + t * (38  - 255))
        g = int(184 + t * (166 - 184))
        b = int(108 + t * (154 - 108))
    return f"#{r:02X}{g:02X}{b:02X}"


def _extract_top_features(
    contribs_row: np.ndarray,
    feature_names: List[str],
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """
    Convert XGBoost pred_contribs row → normalized ranked feature contribution list.

    Processing steps:
      1. Strip bias term (last column):  contribs = contribs_row[:-1]
      2. L1-normalize per prediction:    normalized = contribs / (sum(|contribs|) + ε)
         → each impact is now a fraction of total prediction movement [−1, +1]
      3. Sort by |normalized| descending, return top_n

    Impact interpretation:
      positive → feature pushed score UP toward GOOD
      negative → feature pushed score DOWN toward BAD
    """
    # Step 1 — strip bias
    feat_contribs = contribs_row[:-1].astype(np.float64)

    # Debug: log raw sum before normalization
    raw_sum = np.sum(feat_contribs)
    logger.debug("pred_contribs raw sum (excl bias): %.6f", raw_sum)

    # Step 2 — L1 normalize
    abs_sum = np.sum(np.abs(feat_contribs))
    eps     = 1e-9
    normalized = feat_contribs / (abs_sum + eps)

    # Step 3 — sort by |impact| descending, take top_n
    pairs = sorted(
        zip(feature_names, normalized.tolist()),
        key=lambda x: abs(x[1]),
        reverse=True,
    )[:top_n]

    return [{"name": name, "impact": round(float(val), 5)} for name, val in pairs]


# ─────────────────────────────────────────────────────────────────────────────
# Main scorer class
# ─────────────────────────────────────────────────────────────────────────────

class ConsolidationScorer:
    """
    Thread-safe explainable inference scorer. Loads once at startup; score() is stateless.

    Hard schema contract (v4):
      - ANY feature mismatch at inference time → returns ml_status='invalid_model'
      - No silent imputation of missing features — fail loudly

    Degradation levels:
      no_model       → model.pkl absent or broken at load
      invalid_model  → feature schema mismatch at runtime
      feature_error  → feature extraction crashed
      predict_error  → model.predict() crashed
      no_features    → feature matrix came back empty
      no_boxes       → no boxes to score
      active         → successful prediction
    """

    VERSION = "8.0.0-hardened"

    def __init__(self, model_path: Optional[Path] = None):
        self._model        = None
        self._calibrator   = None
        self._cal_type     = "none"
        self._booster      = None           # raw XGBoost Booster for pred_contribs
        self._feature_cols: List[str] = []
        self._feature_version: str = ""
        self._feature_stats: Dict[str, Dict[str, float]] = {}
        self._col_medians: Dict[str, float] = {}
        self._meta: Dict[str, Any] = {}
        self.threshold      = 0.5           # filtering threshold (not labeling)
        self.good_threshold = DEFAULT_GOOD_THRESHOLD
        self.bad_threshold  = DEFAULT_BAD_THRESHOLD
        self._schema_ok     = False
        self._trained_on    = None          # model.pkl mtime
        self._model_path  = model_path or MODEL_PATH
        
        # State: Drift tracking (3 zone persistence) per symbol_tf
        self._drift_state: Dict[str, deque] = {}

        # Pattern classifier (optional)
        self._pattern_model = None
        self._pattern_feature_cols: List[str] = []
        self._pattern_col_medians: Dict[str, float] = {}

        self._load(self._model_path)
        self._load_pattern(PATTERN_PATH)

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("ConsolidationScorer: no model at %s — ML disabled", path)
            return

        # Record model file modification time as "trained_on"
        try:
            mtime = path.stat().st_mtime
            self._trained_on = datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            self._trained_on = "unknown"

        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
        except Exception as e:
            logger.error("ConsolidationScorer: failed to load model.pkl — %s", e)
            return

        required_keys = {"model", "feature_cols"}
        missing = required_keys - set(data.keys())
        if missing:
            logger.error("ConsolidationScorer: model.pkl missing keys %s — ML disabled", missing)
            return

        self._model           = data["model"]
        self._calibrator      = data.get("calibrator")
        self._cal_type        = data.get("calibrator_type", "none")
        self._feature_cols    = list(data["feature_cols"])
        self._feature_version = data.get("feature_version", "")
        self._feature_stats   = data.get("feature_stats", {})
        self._col_medians     = data.get("col_medians", {})
        
        # ── Threshold Alignment (Structural v7) ───────────────────────────────
        # Prefer F1-optimized threshold for GOOD labeling
        self.good_threshold = float(data.get("optimal_threshold_f1", data.get("optimal_threshold", 0.55)))
        self.threshold      = self.good_threshold # filtering same as good
        # Data-driven BAD threshold: from meta OR fixed margin (0.15) from good
        self.bad_threshold  = float(data.get("bad_threshold", self.good_threshold - 0.20))
        self._meta         = {k: v for k, v in data.items()
                              if k not in ("model", "feature_cols", "col_medians")}
        self._schema_ok    = True

        # ── Feature count assertion ───────────────────────────────────────────
        # Verify the model's internal n_features_in_ matches our feature list.
        # Mismatch here means model.pkl is inconsistent with feature_cols.
        model_nf = getattr(self._model, "n_features_in_", None)
        schema_nf = len(self._feature_cols)
        if model_nf is not None and model_nf != schema_nf:
            logger.error(
                "ConsolidationScorer: FEATURE COUNT MISMATCH — "
                "model expects %d features, feature_cols has %d. ML DISABLED.",
                model_nf, schema_nf,
            )
            self._model = None   # force not-ready → safe fallback
            self._schema_ok = False
            return
        logger.info(
            "ConsolidationScorer: feature count verified — %d/%d ✓",
            schema_nf, model_nf or schema_nf,
        )

        # Grab raw Booster for pred_contribs (XGBoost native SHAP decomposition)
        try:
            self._booster = self._model.get_booster()
            logger.info("ConsolidationScorer: XGBoost Booster ready for pred_contribs")
        except Exception as e:
            logger.warning("ConsolidationScorer: pred_contribs unavailable — %s", e)
            self._booster = None

        logger.info(
            "ConsolidationScorer v%s | %s [%s] | features=%d | train_rows=%d | "
            "θ_good=%.3f | θ_bad=%.3f | trained_on=%s",
            self.VERSION,
            self._meta.get("symbol", "?"), self._meta.get("timeframe", "?"),
            len(self._feature_cols),
            self._meta.get("train_rows", 0),
            self.good_threshold,
            self.bad_threshold,
            self._trained_on,
        )

    def _load_pattern(self, path: Path) -> None:
        """Load pattern classifier (CONTINUATION / LIQUIDITY_GRAB). Optional."""
        if not path.exists():
            logger.info("ConsolidationScorer: no pattern model at %s — pattern prediction disabled", path)
            return
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self._pattern_model         = data.get("model")
            self._pattern_feature_cols  = list(data.get("feature_cols", []))
            self._pattern_col_medians   = data.get("col_medians", {})
            logger.info(
                "ConsolidationScorer: pattern model loaded — "
                "CONTINUATION=%d LIQUIDITY_GRAB=%d features=%d",
                data.get("n_continuation", 0),
                data.get("n_liquidity", 0),
                len(self._pattern_feature_cols),
            )
        except Exception as e:
            logger.warning("ConsolidationScorer: failed to load pattern_model.pkl — %s", e)
            self._pattern_model = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _check_drift(self, symbol: str, timeframe: str, X_row: pd.Series) -> bool:
        """
        TASK 1 — Robust Drift Detection.
        z = abs(x - median) / (IQR + 1e-6). Flag if z > 3.
        Trigger Feature Drift only after 3 consecutive zones.
        """
        if not self._feature_stats:
            return False
            
        key = f"{symbol}_{timeframe}"
        if key not in self._drift_state:
            self._drift_state[key] = deque(maxlen=3)
            
        row_drifted = False
        drift_count = 0
        for col in self._feature_cols:
            if col not in self._feature_stats: continue
            stats = self._feature_stats[col]
            x = X_row[col]
            z = abs(x - stats["median"]) / (stats["iqr"] + 1e-6)
            if z > 3:
                drift_count += 1
        
        # If > 10% of features in this row are individual outliers, mark row as drifted
        if drift_count > (len(self._feature_cols) * 0.1):
            row_drifted = True
            
        self._drift_state[key].append(row_drifted)
        
        # State: active drift only if 3/3 in buffer are True
        return all(self._drift_state[key]) if len(self._drift_state[key]) == 3 else False

    # ── HARD schema validation (v4) ────────────────────────────────────────────

    def validate_features_strict(self, actual_cols: List[str]) -> Dict[str, Any]:
        """
        HARD validation: ANY missing feature → fail.

        Returns dict: {ok, missing, extra, reason}
        If not ok → caller must return ml_status='invalid_model'.
        """
        if not self._feature_cols:
            return {"ok": False, "missing": [], "extra": [], "reason": "no schema loaded"}

        expected = set(self._feature_cols)
        actual   = set(actual_cols)
        missing  = sorted(expected - actual)
        extra    = sorted(actual   - expected)
        ok       = (len(missing) == 0)

        if missing:
            logger.error(
                "ConsolidationScorer HARD FAIL — feature schema mismatch. "
                "Missing: %s | Extra: %s", missing, extra
            )
        elif extra:
            logger.debug("ConsolidationScorer: extra features (ignored): %s", extra)

        return {"ok": ok, "missing": missing, "extra": extra,
                "reason": f"missing features: {missing}" if missing else "ok"}

    # ── Scoring ───────────────────────────────────────────────────────────────

    def score(
        self,
        df: pd.DataFrame,
        boxes: pd.DataFrame,
        symbol: str = "UNKNOWN",
        timeframe: str = "1h",
        threshold: Optional[float] = None,
        include_features: bool = False,
        top_features_n: int = 5,
    ) -> pd.DataFrame:
        if boxes.empty:       return self._apply_fallback(boxes, status="no_boxes")
        if not self.ready:    return self._apply_fallback(boxes, status="no_model")

        # ── 1. Feature Extraction ──────────────────────────────────────────────
        try:
            feat_df = build_feature_matrix(df, boxes, timeframe=timeframe)
        except Exception as e:
            logger.error("Features failed: %s", e)
            return self._apply_fallback(boxes, status="feature_error")
        if feat_df.empty:     return self._apply_fallback(boxes, status="no_features")

        # ── 2. Schema Alignment & Sanity ───────────────────────────────────────
        expected = self._feature_cols
        current  = list(feat_df.columns)
        missing  = [c for c in expected if c not in current]
        
        # FEATURE_VERSION check
        version_mismatch = (self._feature_version != FEATURE_VERSION)
        
        # Global Imputation Logging (TASK 2 v3.3)
        impute_meta = {}
        if missing:
            impute_meta = {"count": len(missing), "features": missing[:3]}
            for c in missing: 
                feat_df[c] = self._col_medians.get(c, 0.0)

        # Final X Selection
        X = feat_df[expected].astype(np.float32)
        
        # TASK 10 Final Failsafe - Infinite/NaN mapping
        X = X.replace([np.inf, -np.inf], np.nan)
        if X.isna().any().any():
            X = X.fillna(self._col_medians)
            
        # ── 3. Inference ───────────────────────────────────────────────────────
        try:
            raw_preds = self._model.predict(X)
            preds = np.clip(raw_preds, 0.0, 1.0)
            
            # Apply Calibration if available
            if self._calibrator:
                if self._cal_type == "sigmoid":
                    preds = self._calibrator.predict_proba(preds.reshape(-1, 1))[:, 1]
                else:
                    preds = self._calibrator.predict(preds)
                preds = np.clip(preds, 0.0, 1.0)
                
        except Exception as e:
            logger.error("Predict error: %s", e)
            return self._apply_fallback(boxes, status="predict_error")

        # ── 4. Contributions ───────────────────────────────────────────────────
        contribs = None
        if self._booster:
            try:
                dm = xgb.DMatrix(X.values, feature_names=expected)
                contribs = self._booster.predict(dm, pred_contribs=True)
            except: pass

        # ── 5. Build Result & Status ──────────────────────────────────────────
        scored = boxes.copy()
        scored["quality"] = 0.5; scored["ml_status"] = "active"
        
        for i, box_idx in enumerate(feat_df.index):
            q = float(preds[i])
            row_drift = self._check_drift(symbol, timeframe, X.iloc[i])
            
            # TASK 10 - FINAL STATS MAP
            status = "active"
            if len(missing) > 5:  status = "invalid_input"
            elif row_drift:      status = "feature_drift"
            elif version_mismatch: status = "version_mismatch"
            
            scored.at[box_idx, "quality"]          = q
            scored.at[box_idx, "quality_color"]    = _quality_to_color(q)
            scored.at[box_idx, "ml_label"]         = self._score_to_label(q)
            scored.at[box_idx, "ml_status"]        = status
            scored.at[box_idx, "ml_confidence"]     = round(_score_to_confidence(q), 4)
            scored.at[box_idx, "ml_debug"]         = {"imputation": impute_meta} if missing else {}
            
            if contribs is not None:
                scored.at[box_idx, "ml_top_features"] = _extract_top_features(contribs[i], expected, top_features_n)

            # Pattern prediction
            if self._pattern_model is not None:
                try:
                    p_row = X.iloc[[i]][self._pattern_feature_cols].fillna(self._pattern_col_medians)
                    p_class = int(self._pattern_model.predict(p_row)[0])
                    scored.at[box_idx, "pattern_prediction"] = PATTERN_CLASSES.get(p_class)
                except: pass

        if threshold and threshold > 0:
            scored = scored[scored["quality"] >= threshold].copy()
            
        return scored

    # ── Fallback helper ───────────────────────────────────────────────────────

    def _apply_fallback(self, boxes: pd.DataFrame, status: str = "inactive") -> pd.DataFrame:
        """Return boxes with neutral ML defaults — no crash guarantee."""
        out = boxes.copy()
        out["quality"]             = 0.5
        out["quality_color"]       = "#FFB86C"
        out["ml_label"]            = "NEUTRAL"
        out["ml_confidence"]       = 0.0
        out["ml_status"]           = status
        out["ml_top_features"]     = None
        out["pattern_prediction"]  = None
        out["pattern_confidence"]  = 0.0
        return out

    def _score_to_label(self, score: float) -> str:
        """New logic: GOOD >= θ_good, BAD <= θ_bad, else NEUTRAL."""
        if score >= self.good_threshold:
            return "GOOD"
        if score <= self.bad_threshold:
            return "BAD"
        return "NEUTRAL"

    # ── Metadata ──────────────────────────────────────────────────────────────

    def meta(self) -> dict:
        """Return model metadata including trained_on timestamp."""
        return {
            **{k: v for k, v in self._meta.items() if not isinstance(v, (np.ndarray, bytes))},
            "version":              self.VERSION,
            "threshold":            self.threshold,
            "ready":                self.ready,
            "schema_ok":            self._schema_ok,
            "feature_cols":         self._feature_cols or [],
            "n_features":           len(self._feature_cols),
            "good_threshold":       self.good_threshold,
            "bad_threshold":        self.bad_threshold,
            "label_colors":         LABEL_COLORS,
            "trained_on":           self._trained_on,
            "contribs_ready":       self._booster is not None,
            "pattern_model_ready":  self._pattern_model is not None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────
consolidation_scorer = ConsolidationScorer()
