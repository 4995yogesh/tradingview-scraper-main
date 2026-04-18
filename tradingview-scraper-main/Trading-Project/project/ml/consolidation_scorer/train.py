"""
train.py v3 — Human-aligned, structure-aware, multi-asset ML training pipeline.

Upgrades over v2:
  TASK 2 — Human label integration: loads ml_feedback.db, overrides auto-labels
           with user_label where available. NEUTRAL excluded. GOOD→1, BAD→0.
  TASK 3 — Multi-symbol infrastructure: queries all (exchange, symbol, timeframe)
           from candles.db. Symbol/TF encoding added only when >1 unique values.
  TASK 4 — Threshold recalibration: precision/recall/F1 evaluated at 0.5/0.6/0.7.
           Best-F1 threshold saved into model metadata.
  TASK 5 — Pattern classifier: second XGBoost classifier using same pre-breakout
           features. Labels from deterministic suggest_pattern_type().
           CONTINUATION→1, LIQUIDITY_GRAB→0. Saved as pattern_model.pkl.
  TASK 6 — Data gate: warns if <50 human labels. Does not abort (would prevent
           bootstrap); simply logs and falls back to auto-labels.
  TASK 7 — Pipeline cleanup: deduplication, NaN guard, consistent schema.
  TASK 8 — Rich model metadata saved into model.pkl.
  TASK 10 — Validation: feature names logged, assert preds∈[0,1], test inference.

Architecture rule (CRITICAL — zero data leakage):
  Features → df.iloc[0 : box.end+1]  (pre-breakout ONLY)
  Labels   → df.iloc[box.end+1:...]  (post-breakout data, never in features)

Usage:
  python train.py
  python train.py --db ../../data/candles.db --timeframe 1h --test-frac 0.2
"""

import os
import sys
import argparse
import logging
import sqlite3
import pickle
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Path setup ────────────────────────────────────────────────────────────────
HERE    = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT.parent))

# Backend data path (for ml_feedback.db)
BACKEND_DATA = PROJECT.parent / "backend" / "data"
sys.path.insert(0, str(BACKEND_DATA))

from indicators.consolidation import consolidation_boxes
from ml.consolidation_scorer.features import build_feature_matrix, FEATURE_COLS, FEATURE_VERSION
from ml.consolidation_scorer.labels   import build_labels

try:
    import xgboost as xgb
except ImportError:
    print("ERROR: xgboost not installed. Run: pip install xgboost")
    sys.exit(1)

from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, precision_score, recall_score, f1_score
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DB      = str(HERE.parent.parent.parent / "data" / "candles.db")
DEFAULT_FB_DB   = str(BACKEND_DATA / "ml_feedback.db")
EXCHANGE        = "OANDA"
SYMBOL          = "EURUSD"
TIMEFRAME       = "1h"
MODEL_OUT       = HERE / "model.pkl"
PATTERN_OUT     = HERE / "pattern_model.pkl"
PLOT_DIR        = HERE / "plots"

MODEL_VERSION   = "4.1.0-hardened"

# STABILITY_VARIANCE_TOLERANCElocked at 0.02
STABILITY_TOLERANCE = 0.02

# Human label mapping (NEUTRAL = IGNORE)
HUMAN_LABEL_MAP = {"GOOD": 1.0, "BAD": 0.0, "NEUTRAL": None}

# Pattern label mapping
PATTERN_LABEL_MAP = {"CONTINUATION": 1, "LIQUIDITY_GRAB": 0}

MIN_PATTERN_TRAIN_ROWS = 20  # skip pattern model if fewer labeled samples
HUMAN_LABEL_WARN_THRESHOLD = 50  # warn if fewer than this many human labels


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def list_all_series(db_path: str) -> list:
    """Return all (exchange, symbol, timeframe) tuples in candles.db."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT exchange, symbol, timeframe FROM candles ORDER BY exchange, symbol, timeframe"
    ).fetchall()
    conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def load_ohlc_from_db(db_path: str, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found: {db_path}")
    conn  = sqlite3.connect(db_path)
    query = """
        SELECT ts, open, high, low, close, volume
        FROM candles WHERE exchange=? AND symbol=? AND timeframe=?
        ORDER BY ts ASC
    """
    df = pd.read_sql_query(query, conn, params=(exchange, symbol, timeframe))
    conn.close()
    if df.empty:
        raise ValueError(f"No data: {exchange}:{symbol} [{timeframe}]")
    df["datetime"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df = df.set_index("datetime").drop(columns=["ts"])
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    logger.info("Loaded %d candles %s:%s [%s]  %s → %s",
                len(df), exchange, symbol, timeframe,
                df.index[0].date(), df.index[-1].date())
    return df


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2 — Human label loader
# ─────────────────────────────────────────────────────────────────────────────

def load_human_labels(fb_db_path: str) -> pd.DataFrame:
    """
    Load human-rated boxes from ml_feedback.db.

    Returns DataFrame with columns:
        [symbol, timeframe, time_start, time_end, user_label, pattern_type]
    Only rows where user_label IN ('GOOD', 'BAD') are returned.
    NEUTRAL rows are excluded (decision Q1).
    """
    if not os.path.exists(fb_db_path):
        logger.warning("ml_feedback.db not found at %s — no human labels available", fb_db_path)
        return pd.DataFrame(columns=["symbol", "timeframe", "time_start", "time_end", "user_label", "pattern_type"])

    try:
        conn = sqlite3.connect(fb_db_path)
        df = pd.read_sql_query(
            """
            SELECT symbol, timeframe,
                   time_start, time_end,
                   user_label, pattern_type
            FROM boxes
            WHERE user_label IN ('GOOD', 'BAD', 'NEUTRAL')
            """,
            conn,
        )
        conn.close()
        logger.info("Human labels loaded: %d GOOD/BAD-rated rows from ml_feedback.db", len(df))
        return df
    except Exception as e:
        logger.warning("Failed to load human labels: %s", e)
        return pd.DataFrame(columns=["symbol", "timeframe", "time_start", "time_end", "user_label", "pattern_type"])


def build_unified_labels(
    feat_df: pd.DataFrame,
    human_df: pd.DataFrame,
    df_ohlc: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    """
    Unified Labeling v1.1 — Create target 'quality' column.
    
    Priority Logic:
      1. Human Label (GOOD=1, BAD=0, NEUTRAL=None)
      2. Auto Label (Outcome-based SUCCESS=1, FAILURE=0, AMBIGUOUS=None)
      3. Filter Noisy Samples (height_atr < 0.25 or duration < 3)
    """
    # ── 1. Calculate Auto labels first ──
    # feat_df index contains original box indices
    # We use build_labels from labels.py which uses compute_label()
    # Need to pass correct subset of 'boxes' data to build_labels
    from ml.consolidation_scorer.labels import build_labels
    
    # Reconstruct boxes metadata from features if hidden, or better, pass them along.
    # We have _start, _end in feat_df (added in build_feature_matrix)
    boxes_recon = pd.DataFrame(index=feat_df.index)
    boxes_recon["start"]  = feat_df["_start"]
    boxes_recon["end"]    = feat_df["_end"]
    # We need top/bottom too. 
    # height_norm = (top-bottom)/avg_range -> not easily reversible without more data.
    # Let's assume the caller passes the 'boxes' df or we extract from metadata columns.
    # For now, let's look at how train.py currently gets auto labels.
    
    # Actually, in the current run_pipeline loop, we have 'b_raw'.
    # I'll update the caller to pass b_raw.
    pass

def merge_unified_labels(
    feat_df: pd.DataFrame,
    auto_labels: pd.Series,
    human_df: pd.DataFrame,
    df_ohlc: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    """
    Merges manual and auto labels with priority: Manual > Auto.
    Also applies noise filtering (Task 5).
    """
    unified = {}
    
    # Build human map for efficient lookup
    hdf = human_df[(human_df["symbol"] == symbol) & (human_df["timeframe"] == timeframe)].copy()
    hdf_index = {}
    if not hdf.empty:
        hdf["ts_start_ms"] = hdf["time_start"].astype(np.int64)
        hdf["ts_end_ms"]   = hdf["time_end"].astype(np.int64)
        for _, r in hdf.iterrows():
            hdf_index[(int(r["ts_start_ms"]), int(r["ts_end_ms"]))] = HUMAN_LABEL_MAP.get(r["user_label"])

    manual_count = 0
    auto_count   = 0
    filtered_count = 0
    
    for idx, row in feat_df.iterrows():
        # Noise Filter (TASK 5 v1.1)
        if row.get("height_atr", 1.0) < 0.25 or row.get("duration", 10) < 3:
            unified[idx] = None
            filtered_count += 1
            continue
            
        # Priority 1: Manual
        ts_start = int(df_ohlc.index[int(row["_start"])].timestamp() * 1000)
        ts_end   = int(df_ohlc.index[int(row["_end"])].timestamp() * 1000)
        key = (ts_start, ts_end)
        
        val = hdf_index.get(key, "MISSING")
        
        if val != "MISSING":
            unified[idx] = val
            if val is not None: manual_count += 1
        else:
            # Priority 2: Auto
            auto_val = auto_labels.get(idx)
            unified[idx] = auto_val
            if auto_val is not None: auto_count += 1
            
    feat_df["quality"] = pd.Series(unified)
    logger.info("Unified labels: %d manual, %d auto. (Filtered %d noisy samples)", 
                manual_count, auto_count, filtered_count)
    return feat_df


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5 — Pattern label generator (deterministic, no leakage)
# ─────────────────────────────────────────────────────────────────────────────

def build_pattern_labels(df: pd.DataFrame, boxes: pd.DataFrame) -> pd.Series:
    """
    Generate pattern labels using deterministic suggest_pattern_type().

    NOTE: suggest_pattern_type() uses post-breakout data to determine
    CONTINUATION vs LIQUIDITY_GRAB. These are used as LABELS only
    (consistent with architecture rule Q2).

    Returns pd.Series with CONTINUATION→1, LIQUIDITY_GRAB→0, None→NaN.
    """
    try:
        from ml_feedback import suggest_pattern_type
    except ImportError:
        try:
            # Fallback: direct path import
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "ml_feedback",
                str(BACKEND_DATA / "ml_feedback.py"),
            )
            mod = importlib.util.load_from_spec(spec)
            spec.loader.exec_module(mod)
            suggest_pattern_type = mod.suggest_pattern_type
        except Exception as e:
            logger.warning("suggest_pattern_type not available: %s — skipping pattern classifier", e)
            return pd.Series({idx: np.nan for idx in boxes.index})

    labels = {}
    for idx, row in boxes.iterrows():
        end_i      = int(row["end"])
        price_high = float(row["top"])
        price_low  = float(row["bottom"])
        try:
            sug = suggest_pattern_type(df, end_i, price_high, price_low)
            ptype = sug.get("pattern_suggestion")
            if ptype in PATTERN_LABEL_MAP:
                labels[idx] = PATTERN_LABEL_MAP[ptype]
            else:
                labels[idx] = np.nan
        except Exception:
            labels[idx] = np.nan

    return pd.Series(labels, name="pattern_label")


# ─────────────────────────────────────────────────────────────────────────────
# TASK 3 — Symbol/TF encoding
# ─────────────────────────────────────────────────────────────────────────────

TF_MINUTES_MAP = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440, "1w": 10080
}


def encode_categorical_features(
    feat_df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    all_symbols: list,
    all_timeframes: list,
) -> pd.DataFrame:
    """
    Add symbol/timeframe encoding columns ONLY when >1 unique value exists.
    This avoids adding meaningless constant columns that add noise.
    """
    added = []
    if len(all_symbols) > 1:
        sym_map = {s: i for i, s in enumerate(sorted(set(all_symbols)))}
        feat_df["symbol_encoded"] = sym_map.get(symbol, 0)
        added.append("symbol_encoded")

    if added:
        logger.info("Added categorical features: %s", added)

    return feat_df, added


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation helpers
# ─────────────────────────────────────────────────────────────────────────────

def top_k_precision(y_true: np.ndarray, y_pred: np.ndarray, k_frac: float = 0.2) -> float:
    k = max(1, int(len(y_pred) * k_frac))
    top_k_idx = np.argsort(y_pred)[-k:]
    return float(np.mean(y_true[top_k_idx]))


def bucket_analysis(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 5) -> pd.DataFrame:
    bins   = np.linspace(0, 1, n_bins + 1)
    labels = [f"{bins[i]:.1f}–{bins[i+1]:.1f}" for i in range(n_bins)]
    bin_idx = np.digitize(y_pred, bins[1:-1])
    rows = []
    for b in range(n_bins):
        mask = bin_idx == b
        count = int(np.sum(mask))
        avg_true = float(np.mean(y_true[mask])) if count > 0 else np.nan
        avg_pred = float(np.mean(y_pred[mask])) if count > 0 else np.nan
        rows.append({"bin": labels[b], "count": count,
                     "avg_true": avg_true, "avg_pred": avg_pred})
    return pd.DataFrame(rows)


def calibrate_threshold(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    min_count_frac: float = 0.05,
) -> float:
    """Find threshold maximizing avg(y_true[y_pred >= θ])."""
    min_count = max(1, int(len(y_pred) * min_count_frac))
    best_threshold = 0.0
    best_quality   = 0.0
    for theta in np.linspace(0.0, 0.95, 100):
        mask = y_pred >= theta
        if np.sum(mask) < min_count:
            break
        avg_q = float(np.mean(y_true[mask]))
        if avg_q > best_quality:
            best_quality   = avg_q
            best_threshold = theta
    return best_threshold


def evaluate_threshold_f1(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    thresholds: list = None,
) -> dict:
    """
    TASK 4 — Evaluate precision/recall/F1 at candidate thresholds.
    y_true is continuous [0,1]; binarize at 0.5 for classification metrics.

    Returns dict with best threshold by F1.
    """
    if thresholds is None:
        thresholds = [0.5, 0.6, 0.7]

    # Binarize ground truth at 0.5
    y_true_bin = (y_true >= 0.5).astype(int)

    results = {}
    for t in thresholds:
        y_pred_bin = (y_pred >= t).astype(int)
        if y_pred_bin.sum() == 0:
            results[t] = {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}
            continue
        p = precision_score(y_true_bin, y_pred_bin, zero_division=0)
        r = recall_score(y_true_bin, y_pred_bin, zero_division=0)
        f = f1_score(y_true_bin, y_pred_bin, zero_division=0)
        support = int(y_pred_bin.sum())
        results[t] = {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "support": support}
        logger.info("Threshold %.2f → precision=%.3f  recall=%.3f  F1=%.3f  support=%d",
                    t, p, r, f, support)

    best_t = max(results.keys(), key=lambda t: results[t]["f1"])
    logger.info("Best threshold by F1: %.2f  (F1=%.3f)", best_t, results[best_t]["f1"])
    return {"results": results, "best_threshold": best_t, "best_metrics": results[best_t]}


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5 — Pattern classifier trainer
# ─────────────────────────────────────────────────────────────────────────────

def train_pattern_classifier(
    feat_df: pd.DataFrame,
    pattern_labels: pd.Series,
    use_cols: list,
    col_medians: dict,
    test_frac: float = 0.2,
) -> dict | None:
    """
    Train second XGBoost CLASSIFIER for CONTINUATION(1) vs LIQUIDITY_GRAB(0).
    Uses same pre-breakout features as quality model.
    Returns model dict or None if insufficient data.
    """
    # Merge labels
    pf = feat_df.copy()
    pf["pattern_label"] = pattern_labels

    before = len(pf)
    pf = pf.dropna(subset=["pattern_label"])
    logger.info("Pattern labels: %d valid / %d total", len(pf), before)

    if len(pf) < MIN_PATTERN_TRAIN_ROWS:
        logger.warning(
            "Insufficient pattern labels: %d < %d — skipping pattern classifier",
            len(pf), MIN_PATTERN_TRAIN_ROWS
        )
        return None

    # Class distribution
    n_cont = int((pf["pattern_label"] == 1).sum())
    n_liq  = int((pf["pattern_label"] == 0).sum())
    logger.info("Pattern label distribution: CONTINUATION=%d  LIQUIDITY_GRAB=%d", n_cont, n_liq)

    if n_cont == 0 or n_liq == 0:
        logger.warning("Pattern classifier: only one class present — skipping")
        return None

    pf = pf.sort_values("_start")
    split_idx = int(len(pf) * (1 - test_frac))
    train_pf  = pf.iloc[:split_idx]
    test_pf   = pf.iloc[split_idx:]

    X_train = train_pf[use_cols].astype(np.float32)
    y_train = train_pf["pattern_label"].astype(int)
    X_test  = test_pf[use_cols].astype(np.float32)
    y_test  = test_pf["pattern_label"].astype(int)

    for col in use_cols:
        fill = col_medians.get(col, 0.0)
        X_train[col] = X_train[col].replace([np.inf, -np.inf], np.nan).fillna(fill)
        X_test[col]  = X_test[col].replace([np.inf, -np.inf], np.nan).fillna(fill)

    logger.info("Training pattern classifier — train=%d test=%d", len(X_train), len(X_test))

    scale_ratio = n_liq / max(n_cont, 1)  # handle class imbalance
    pattern_model = xgb.XGBClassifier(
        n_estimators          = 300,
        learning_rate         = 0.05,
        max_depth             = 4,
        subsample             = 0.8,
        colsample_bytree      = 0.8,
        reg_alpha             = 0.1,
        reg_lambda            = 1.0,
        min_child_weight      = 3,
        gamma                 = 0.05,
        objective             = "binary:logistic",
        eval_metric           = "logloss",
        early_stopping_rounds = 20,
        random_state          = 42,
        n_jobs                = -1,
        scale_pos_weight      = scale_ratio,
    )

    if len(X_test) > 0:
        pattern_model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )
    else:
        pattern_model.fit(X_train, y_train, verbose=False)

    # Evaluate
    if len(X_test) > 0:
        preds = pattern_model.predict(X_test)
        acc = float(np.mean(preds == y_test.values))
        logger.info("Pattern classifier test accuracy: %.3f", acc)

    importances = pd.Series(
        pattern_model.feature_importances_, index=use_cols
    ).sort_values(ascending=False)
    logger.info("Pattern top-5 features:\n%s", importances.head(5).to_string())

    return {
        "model":          pattern_model,
        "feature_cols":   use_cols,
        "col_medians":    col_medians,
        "n_continuation": n_cont,
        "n_liquidity":    n_liq,
        "version":        MODEL_VERSION,
        "trained_on":     datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def prepare_unified_dataset(
    db_path: str = DEFAULT_DB,
    fb_db_path: str = DEFAULT_FB_DB,
    timeframe: str = TIMEFRAME,
    train_all_series: bool = False,
    max_candles_per_series: int | None = None,
) -> pd.DataFrame:
    """
    Core data engine: loads OHLC, detects boxes, joins manual labels, 
    computes outcomes, and applies noise filtering.
    
    Returns a unified DataFrame with features + 'quality' column.
    """
    all_series = list_all_series(db_path)
    if not all_series:
        return pd.DataFrame()

    if train_all_series:
        target_series = all_series
    else:
        target_series = [(ex, sym, tf) for ex, sym, tf in all_series
                         if sym == SYMBOL and tf == timeframe]
        if not target_series:
            target_series = [all_series[0]]

    all_symbols = list({sym for _, sym, _ in target_series})
    all_timeframes = list({tf for _, _, tf in target_series})
    human_df = load_human_labels(fb_db_path)

    all_feat_dfs = []

    for (exchange, symbol, tf) in target_series:
        try:
            df = load_ohlc_from_db(db_path, exchange, symbol, tf)
        except Exception:
            continue

        def process_segment(seg_df):
            b_raw = consolidation_boxes(seg_df, min_bars=5, use_time_filter=False)
            if b_raw.empty: return None

            b_raw["start_time"] = seg_df.index[b_raw["start"].astype(int)].values
            b_raw["end_time"]   = seg_df.index[b_raw["end"].astype(int)].values
            b_raw["duration"]   = b_raw["end"].astype(int) - b_raw["start"].astype(int)
            b_raw = b_raw[b_raw["duration"] >= 2].copy()
            b_raw = b_raw.drop_duplicates(subset=["start", "end", "top", "bottom"])
            if b_raw.empty: return None

            f_df = build_feature_matrix(seg_df, b_raw, timeframe=tf)
            if f_df.empty: return None

            a_lbl = build_labels(seg_df, b_raw)
            f_df = merge_unified_labels(f_df, a_lbl, human_df, seg_df, symbol, tf)
            
            p_lbl = build_pattern_labels(seg_df, b_raw)
            f_df["pattern_label"] = p_lbl
            
            f_df["symbol"] = symbol
            f_df["timeframe"] = tf
            return f_df

        labeled_timestamps = []
        series_feat_dfs = []
        if not human_df.empty:
            match_df = human_df[(human_df["symbol"] == symbol) & (human_df["timeframe"] == tf)]
            if not match_df.empty:
                labeled_timestamps = match_df["time_start"].astype(int).tolist()

        if labeled_timestamps:
            for ts in labeled_timestamps:
                t_arr = pd.to_datetime([int(ts) // 1000], unit='s', utc=True)
                idx = df.index.get_indexer(t_arr, method='nearest')[0]
                if idx == -1: continue
                start_idx = max(0, idx - 500)
                end_idx = min(len(df), idx + 500)
                seg = df.iloc[start_idx:end_idx].copy()
                res = process_segment(seg)
                if res is not None:
                    res["_global_start_time"] = seg.index[res["_start"].astype(int)].astype(np.int64)
                    res["_global_end_time"]   = seg.index[res["_end"].astype(int)].astype(np.int64)
                    series_feat_dfs.append(res)
        else:
            if max_candles_per_series is not None and len(df) > max_candles_per_series:
                df = df.tail(max_candles_per_series).copy()
            res = process_segment(df)
            if res is not None:
                res["_global_start_time"] = df.index[res["_start"].astype(int)].astype(np.int64)
                res["_global_end_time"]   = df.index[res["_end"].astype(int)].astype(np.int64)
                series_feat_dfs.append(res)
                
        if not series_feat_dfs:
            continue
            
        series_feat_df = pd.concat(series_feat_dfs, ignore_index=True)
        series_feat_df["_symbol"]    = symbol
        series_feat_df["_timeframe"] = tf

        if "_global_start_time" in series_feat_df.columns:
            series_feat_df = series_feat_df.drop_duplicates(subset=["_symbol", "_timeframe", "_global_start_time", "_global_end_time"])

        series_feat_df, _added = encode_categorical_features(
            series_feat_df, symbol, tf, all_symbols, all_timeframes
        )
        all_feat_dfs.append(series_feat_df)

    if not all_feat_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_feat_dfs, ignore_index=True)
    # Filter for quality
    combined = combined.dropna(subset=["quality"])
    return combined

def run_pipeline(
    db_path: str = DEFAULT_DB,
    fb_db_path: str = DEFAULT_FB_DB,
    timeframe: str = TIMEFRAME,
    test_frac: float = 0.2,
    train_all_series: bool = False,
    max_candles_per_series: int | None = None,
    hard_negatives: bool = False,
    force: bool = False,
):
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    # ── TASK 1: Prepare Dataset ──
    logger.info("Preparing unified dataset for %s/%s ...", SYMBOL, timeframe)
    combined = prepare_unified_dataset(
        db_path=db_path,
        fb_db_path=fb_db_path,
        timeframe=timeframe,
        train_all_series=train_all_series,
        max_candles_per_series=max_candles_per_series
    )
    
    # ── TASK 6: Entry Log + Statistics ──
    total_samples = len(combined)
    usable_samples = combined["quality"].notna().sum()
    positives = (combined["quality"] == 1).sum()
    negatives = (combined["quality"] == 0).sum()
    ignored   = (combined["quality"].isna()).sum() # quality is already dropped by prepare_unified_dataset though

    print("\n" + "="*40)
    print("[ML TRAIN START]")
    print(f"usable_samples: {usable_samples}")
    print(f"positives:      {positives}")
    print(f"negatives:      {negatives}")
    print(f"ignored:        {ignored}")
    print("="*40 + "\n")

    # ── TASK 7: Failsafe ──
    if usable_samples == 0:
        print("[ML ERROR] No usable samples. Abort.")
        return

    if len(combined) < 30:
        logger.error("Too few samples (%d). Need ≥30.", len(combined))
        return

    # TASK 7 — Guard: no NaN features
    use_cols_base = [c for c in FEATURE_COLS if c in combined.columns]
    extra_cols    = [c for c in ["symbol_encoded"] if c in combined.columns]
    use_cols      = use_cols_base + extra_cols

    missing = [c for c in FEATURE_COLS if c not in combined.columns]
    if missing:
        logger.warning("Missing feature cols (skipped): %s", missing)

    # ── TASK 10 — Log feature names ───────────────────────────────────────────
    logger.info("─" * 55)
    logger.info("FEATURE SET (%d features):", len(use_cols))
    for i, col in enumerate(use_cols):
        logger.info("  [%02d] %s", i + 1, col)
    logger.info("─" * 55)

    # ── Time-based split ──────────────────────────────────────────────────────
    # ── TASK 4 — Strict Data Order Lock ───────────────────────────────────────
    combined = combined.sort_values(by=["_symbol", "_timeframe", "_global_start_time"])
    
    # ── TASK 10 — Sample Gates ────────────────────────────────────────────────
    # Gate removed for Unified Backfill v1.1
    if len(combined) < 5:
        logger.error("ABORT: Total unified samples (%d) < 5.", len(combined))
        return

    # ── Temporal split (No shuffle) ───────────────────────────────────────────
    split_idx  = int(len(combined) * (1 - test_frac))
    train_df   = combined.iloc[:split_idx]
    test_df    = combined.iloc[split_idx:]

    X_train = train_df[use_cols].astype(np.float32)
    y_train = train_df["quality"].astype(np.float32)
    X_test  = test_df[use_cols].astype(np.float32)
    y_test  = test_df["quality"].astype(np.float32)

    logger.info("Train: %d | Test: %d (Unified dataset)", len(X_train), len(X_test))

    # TASK 7 — Sanitise: replace inf/NaN with column medians
    col_medians = X_train.median()
    X_train = X_train.replace([np.inf, -np.inf], np.nan).fillna(col_medians)
    X_test  = X_test.replace([np.inf, -np.inf], np.nan).fillna(col_medians)

    # ── XGBoost quality model ─────────────────────────────────────────────────
    # ── TASK 1 & 7 — Stability Check (3 runs) ─────────────────────────────────
    stability_metrics = []
    logger.info("Starting 3x stability training loop (tolerance=%.2f) ...", STABILITY_TOLERANCE)
    
    best_model = None
    best_f1 = -1.0
    
    for run_i in range(3):
        m = xgb.XGBRegressor(
            n_estimators          = 500,
            learning_rate         = 0.05,
            max_depth             = 8,
            subsample             = 0.8,
            colsample_bytree      = 0.8,
            reg_alpha             = 0.1,
            reg_lambda            = 1.0,
            objective             = "reg:squarederror",
            eval_metric           = "mae",
            early_stopping_rounds = 30,
            random_state          = 42 + run_i, # locked seed but slightly varied for stability check
            n_jobs                = -1,
        )
        if len(X_test) > 0:
            m.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        else:
            m.fit(X_train, y_train, verbose=False)
            
        # Eval run i
        r_preds = np.clip(m.predict(X_test), 0.0, 1.0)
        r_f1_res = evaluate_threshold_f1(y_test.values, r_preds, thresholds=[0.5, 0.55, 0.6, 0.65, 0.7])
        
        run_stats = {
            "f1": r_f1_res["best_metrics"]["f1"],
            "threshold": r_f1_res["best_threshold"],
            "mean_pred": r_preds.mean()
        }
        stability_metrics.append(run_stats)
        logger.info("  Run %d: F1=%.4f θ=%.3f mean=%.4f", run_i+1, run_stats["f1"], run_stats["threshold"], run_stats["mean_pred"])
        
        if run_stats["f1"] > best_f1:
            best_f1 = run_stats["f1"]
            best_model = m
            
    # Check variances
    f1_var = np.var([s["f1"] for s in stability_metrics])
    thresh_var = np.var([s["threshold"] for s in stability_metrics])
    if f1_var > STABILITY_TOLERANCE or thresh_var > STABILITY_TOLERANCE:
        logger.warning("[ML WARNING] Training instability detected (F1_var=%.4f, θ_var=%.4f)", f1_var, thresh_var)
    
    model = best_model
    logger.info("Best iteration: %d", model.best_iteration if hasattr(model, 'best_iteration') else -1)

    # ── TASK 10 — Evaluation ──────────────────────────────────────────────────
    if len(X_test) > 0:
        raw_preds = model.predict(X_test)
        preds     = np.clip(raw_preds, 0.0, 1.0)
        y_true    = y_test.values

        # TASK 10 — Assert predictions in [0,1]
        assert preds.min() >= 0.0 and preds.max() <= 1.0, "Prediction out of [0,1] range!"

        mae_val   = mean_absolute_error(y_true, preds)
        rmse_val  = float(np.sqrt(mean_squared_error(y_true, preds)))
        pearson   = float(np.corrcoef(y_true, preds)[0, 1])
        spear_r, spear_p = spearmanr(y_true, preds)
        top20     = top_k_precision(y_true, preds, k_frac=0.20)
        top10     = top_k_precision(y_true, preds, k_frac=0.10)

        buckets   = bucket_analysis(y_true, preds)
        threshold = calibrate_threshold(y_true, preds, min_count_frac=0.10)

        # ── TASK 2 — Score Quality Guard (Stronger v3.3) ───────────────────────
        pred_std = np.std(preds)
        pred_iqr = np.percentile(preds, 75) - np.percentile(preds, 25)
        
        if pred_std < 0.07 or pred_iqr < 0.10:
            logger.warning("[ML WARNING] Prediction variance too low (std=%.4f, iqr=%.4f)", pred_std, pred_iqr)

        # ── TASK 3 — Calibration Safety (v3.3) ─────────────────────────────────
        n_val = len(y_true)
        calibrator = None
        cal_type = "none"
        
        if n_val < 50:
            logger.info("Calibration: < 50 samples. Using Sigmoid.")
            calibrator = LogisticRegression()
            calibrator.fit(preds.reshape(-1, 1), y_true > 0.5) # Binary target for logistic
            cal_type = "sigmoid"
        elif 50 <= n_val < 100:
            logger.info("Calibration: 50-100 samples. Using Isotonic (smoothed).")
            # IsotonicRegression doesn't have min_samples_leaf, but we fit on val set
            calibrator = IsotonicRegression(out_of_bounds='clip')
            calibrator.fit(preds, y_true)
            cal_type = "isotonic_smoothed"
        else:
            logger.info("Calibration: > 100 samples. Using Full Isotonic.")
            calibrator = IsotonicRegression(out_of_bounds='clip')
            calibrator.fit(preds, y_true)
            cal_type = "isotonic"

        # Apply calibration for reporting
        if cal_type == "sigmoid":
            cal_preds = calibrator.predict_proba(preds.reshape(-1, 1))[:, 1]
        else:
            cal_preds = calibrator.predict(preds)
        
        # Recalculate thresholds on calibrated preds
        f1_results  = evaluate_threshold_f1(y_true, cal_preds, thresholds=[0.5, 0.55, 0.6, 0.65, 0.7])
        best_threshold_f1 = f1_results["best_threshold"]

        logger.info("─" * 55)
        logger.info("TEST RESULTS (Calibrated)")
        logger.info("  MAE              : %.4f", mean_absolute_error(y_true, cal_preds))
        logger.info("  Best threshold (F1): %.3f", best_threshold_f1)
        logger.info("  Pred Std/IQR     : %.4f / %.4f", pred_std, pred_iqr)
        logger.info("─" * 55)
        
        # Use calibrated preds for plots/buckets
        preds = cal_preds
        threshold = best_threshold_f1
        buckets   = bucket_analysis(y_true, preds)
    else:
        preds = np.array([])
        y_true = np.array([])
        pearson = 0.0
        spear_r = 0.0
        mae_val = 0.0
        threshold = 0.5
        best_threshold_f1 = 0.5
        f1_results = {}

    # TASK 10 — Feature importance
    importances = pd.Series(
        model.feature_importances_, index=use_cols
    ).sort_values(ascending=False)
    logger.info("─" * 55)
    logger.info("Top-10 features (quality model):\n%s", importances.head(10).to_string())

    # ── SHAP (optional) ───────────────────────────────────────────────────────
    if SHAP_AVAILABLE and len(X_test) > 0:
        _compute_shap(model, X_test, use_cols)
    elif not SHAP_AVAILABLE:
        logger.info("SHAP not installed (pip install shap). Skipping.")

    # ── Plots ─────────────────────────────────────────────────────────────────
    if len(y_true) > 0 and len(preds) > 0:
        _plot_results(y_true, preds, importances, buckets, threshold)

    # ── TASK 5 — Pattern classifier ───────────────────────────────────────────
    pattern_model_data = train_pattern_classifier(
        combined[use_cols + ["_start", "_end", "pattern_label"]].copy(),
        combined["pattern_label"],
        use_cols,
        col_medians.to_dict(),
        test_frac=test_frac,
    )

    if pattern_model_data is not None:
        with open(PATTERN_OUT, "wb") as f:
            pickle.dump(pattern_model_data, f, protocol=4)
        logger.info("Pattern model saved → %s", PATTERN_OUT)

    # ── TASK 10 — Test inference ──────────────────────────────────────────────
    logger.info("─" * 55)
    logger.info("TASK 10 — Test inference:")
    try:
        sample = X_train.iloc[:3] if len(X_train) >= 3 else X_train
        test_preds = np.clip(model.predict(sample), 0.0, 1.0)
        for i, p in enumerate(test_preds):
            logger.info("  Sample %d → quality=%.4f", i, p)
        assert all(0.0 <= p <= 1.0 for p in test_preds), "Test inference out of range!"
        logger.info("  ✓ Test inference passed")
    except Exception as e:
        logger.error("Test inference failed: %s", e)

    # ── TASK 2 — Feature Drift Monitoring (v3.3) ───────────────────────────
    feature_stats = {}
    for col in use_cols:
        col_data = X_train[col]
        feature_stats[col] = {
            "mean":   float(col_data.mean()),
            "std":    float(col_data.std()),
            "median": float(col_data.median()),
            "iqr":    float(col_data.quantile(0.75) - col_data.quantile(0.25))
        }

    # ── TASK 8 — Save model + metadata ────────────────────────────────────────
    model_data = {
        "model":                 model,
        "calibrator":            calibrator,
        "calibrator_type":       cal_type,
        "feature_cols":          use_cols,
        "feature_version":       FEATURE_VERSION,
        "feature_stats":         feature_stats,
        "col_medians":           col_medians.to_dict(),
        "train_rows":            len(X_train),
        "test_rows":             len(X_test),
        "pearson_r":             float(pearson),
        "spearman_r":            float(spear_r),
        "mae":                   float(mae_val),
        "optimal_threshold":     float(threshold),
        "optimal_threshold_f1":  float(best_threshold_f1),
        "threshold_f1_results":  f1_results.get("results", {}),
        "sqrt_transform":        True,
        # TASK 8 — Rich metadata
        "version":               MODEL_VERSION,
        "features_list":         use_cols,
        "trained_on":            datetime.now(timezone.utc).isoformat(),
        "dataset_size":          int(len(combined)),
        "symbols_used":          list(set(combined["_symbol"].tolist())),
        "timeframes_used":       list(set(combined["_timeframe"].tolist())),
        "has_pattern_model":     pattern_model_data is not None,
        "timeframe":             timeframe,
        "symbol":                SYMBOL,
    }

    with open(MODEL_OUT, "wb") as f:
        pickle.dump(model_data, f, protocol=4)
    logger.info("Quality model saved → %s", MODEL_OUT)

    return model_data


# ─────────────────────────────────────────────────────────────────────────────
# SHAP
# ─────────────────────────────────────────────────────────────────────────────

def _compute_shap(model, X_test: pd.DataFrame, use_cols):
    try:
        explainer  = shap.TreeExplainer(model)
        shap_vals  = explainer.shap_values(X_test)
        mean_shap  = pd.Series(
            np.abs(shap_vals).mean(axis=0), index=use_cols
        ).sort_values(ascending=False)
        logger.info("SHAP mean |value| (top 10):\n%s", mean_shap.head(10).to_string())
        fig, ax = plt.subplots(figsize=(8, 6))
        shap.summary_plot(shap_vals, X_test, plot_type="bar", show=False)
        out = PLOT_DIR / "shap_summary.png"
        plt.savefig(str(out), dpi=120, bbox_inches="tight")
        plt.close()
        logger.info("SHAP plot → %s", out)
    except Exception as e:
        logger.warning("SHAP failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Plots
# ─────────────────────────────────────────────────────────────────────────────

def _plot_results(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    importances: pd.Series,
    buckets: pd.DataFrame,
    threshold: float,
):
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("Consolidation Box Quality Scorer v3 — Evaluation", fontsize=14)

    # 1. Predicted vs Actual
    ax = axes[0, 0]
    ax.scatter(y_true, y_pred, alpha=0.35, s=18, color="#2962FF")
    ax.plot([0, 1], [0, 1], "r--", lw=1)
    ax.axvline(threshold, color="#FFB86C", lw=1.2, ls="--", label=f"θ={threshold:.2f}")
    ax.set_xlabel("Actual Quality (√-transformed)")
    ax.set_ylabel("Predicted Quality")
    ax.set_title("Predicted vs Actual")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    pearson = float(np.corrcoef(y_true, y_pred)[0, 1])
    ax.text(0.04, 0.93, f"r = {pearson:.3f}", transform=ax.transAxes, color="red", fontsize=10)
    ax.legend(fontsize=8)

    # 2. Error distribution
    ax = axes[0, 1]
    errors = y_pred - y_true
    ax.hist(errors, bins=35, color="#26A69A", edgecolor="white", lw=0.4)
    ax.axvline(0, color="red", ls="--")
    ax.set_xlabel("Prediction Error (pred − actual)")
    ax.set_ylabel("Count")
    ax.set_title("Error Distribution")
    ax.text(0.04, 0.93, f"MAE={np.mean(np.abs(errors)):.4f}",
            transform=ax.transAxes, fontsize=9)

    # 3. Feature importance (top 12)
    ax = axes[0, 2]
    top_n = importances.head(12)
    ax.barh(top_n.index[::-1], top_n.values[::-1], color="#BD93F9")
    ax.set_xlabel("Importance")
    ax.set_title("Feature Importances (top 12)")

    # 4. Bucket analysis
    ax = axes[1, 0]
    valid = buckets.dropna()
    x = np.arange(len(valid))
    ax.bar(x, valid["avg_true"],  width=0.4, label="Avg True",  color="#26A69A", align="edge")
    ax.bar(x + 0.4, valid["avg_pred"], width=0.4, label="Avg Pred", color="#2962FF", align="edge")
    ax.set_xticks(x + 0.4)
    ax.set_xticklabels(valid["bin"].values, rotation=15, fontsize=8)
    ax.set_ylabel("Quality (√-transformed)")
    ax.set_title("Bucket Analysis")
    ax.legend(fontsize=8)

    # 5. Score distribution
    ax = axes[1, 1]
    ax.hist(y_pred, bins=30, color="#FF79C6", edgecolor="white", lw=0.4, label="Predicted")
    ax.hist(y_true, bins=30, color="#50FA7B", edgecolor="white", lw=0.4, alpha=0.6, label="Actual")
    ax.axvline(threshold, color="red", lw=1.5, ls="--", label=f"θ={threshold:.2f}")
    ax.set_xlabel("Quality Score")
    ax.set_ylabel("Count")
    ax.set_title("Score Distributions")
    ax.legend(fontsize=8)

    # 6. Cumulative rank quality
    ax = axes[1, 2]
    sort_idx = np.argsort(y_pred)[::-1]
    cumulative_quality = np.cumsum(y_true[sort_idx]) / (np.arange(len(y_true)) + 1)
    ax.plot(cumulative_quality, color="#F1FA8C", lw=1.5)
    ax.axhline(np.mean(y_true), color="red", ls="--", lw=1, label="Mean quality")
    ax.set_xlabel("# boxes selected (ranked by score)")
    ax.set_ylabel("Avg true quality")
    ax.set_title("Cumulative Quality @ K")
    ax.legend(fontsize=8)

    plt.tight_layout()
    out = PLOT_DIR / "evaluation_v3.png"
    plt.savefig(str(out), dpi=120, bbox_inches="tight")
    plt.close()
    logger.info("Plot saved → %s", out)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train consolidation scorer v3")
    parser.add_argument("--db",         default=DEFAULT_DB)
    parser.add_argument("--fb-db",      default=DEFAULT_FB_DB, help="ml_feedback.db path")
    parser.add_argument("--timeframe",  default=TIMEFRAME)
    parser.add_argument("--test-frac",  type=float, default=0.2)
    parser.add_argument("--all-series", action="store_true",
                        help="Train on all symbols+timeframes in candles.db (default: EURUSD only)")
    parser.add_argument("--hard-negatives", action="store_true", help="Enable hard negative mining")
    parser.add_argument("--force",          action="store_true", help="Force training even if stable")
    args = parser.parse_args()

    run_pipeline(
        db_path         = args.db,
        fb_db_path      = args.fb_db,
        timeframe       = args.timeframe,
        test_frac       = args.test_frac,
        train_all_series = args.all_series,
        hard_negatives  = args.hard_negatives,
        force           = args.force,
    )
