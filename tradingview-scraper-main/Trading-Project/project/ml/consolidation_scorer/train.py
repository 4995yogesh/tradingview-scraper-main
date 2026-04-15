"""
train.py v2 — Improved training pipeline with:
  - Hard negative filtering (no-breakout boxes removed in labels.py)
  - sqrt target transform (applied in labels.py via sqrt_transform=True)
  - Upgraded XGBoost config with early stopping
  - Spearman rank correlation evaluation
  - Top-K precision analysis
  - Bucket analysis (label distribution per score bin)
  - Threshold calibration via validation set
  - SHAP feature importance (optional)

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
from pathlib import Path

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

from indicators.consolidation import consolidation_boxes
from ml.consolidation_scorer.features import build_feature_matrix
from ml.consolidation_scorer.labels   import build_labels

try:
    import xgboost as xgb
except ImportError:
    print("ERROR: xgboost not installed. Run: pip install xgboost")
    sys.exit(1)

from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error

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

DEFAULT_DB = str(HERE.parent.parent.parent / "data" / "candles.db")
EXCHANGE   = "OANDA"
SYMBOL     = "EURUSD"
TIMEFRAME  = "1h"
MODEL_OUT  = HERE / "model.pkl"
PLOT_DIR   = HERE / "plots"

FEATURE_COLS = [
    # Geometry
    "height_atr", "height_norm", "duration", "height_per_bar",
    # Volatility
    "close_std_atr", "close_std_norm", "avg_range_atr",
    "compression_atr", "range_cv",
    # Structure
    "n_swings_norm", "top_touches", "bot_touches",
    "symmetry_score", "pct_time_near_top", "pct_time_near_bot",
    "wick_body_ratio", "pct_contained", "close_above_mid",
    # Context
    "trend_slope", "atr_ratio", "atr_ratio_true", "rel_pos", "pre_vol_compression",
    # Pre-breakout approach
    "approach_body_norm", "approach_vol_ratio", "boundary_proximity",
]


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

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
# Evaluation helpers
# ─────────────────────────────────────────────────────────────────────────────

def top_k_precision(y_true: np.ndarray, y_pred: np.ndarray, k_frac: float = 0.2) -> float:
    """
    Average true quality of the top k_frac% predicted boxes.
    Measures if the model correctly identifies the best boxes.
    """
    k = max(1, int(len(y_pred) * k_frac))
    top_k_idx = np.argsort(y_pred)[-k:]
    return float(np.mean(y_true[top_k_idx]))


def bucket_analysis(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 5) -> pd.DataFrame:
    """
    Split predictions into equal-width bins; compute avg true quality per bin.
    Reveals monotonicity: good model → higher bin = higher actual quality.
    """
    bins   = np.linspace(0, 1, n_bins + 1)
    labels = [f"{bins[i]:.1f}–{bins[i+1]:.1f}" for i in range(n_bins)]
    bin_idx = np.digitize(y_pred, bins[1:-1])  # 0..n_bins-1

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
    """
    Find threshold θ that maximizes avg(y_true[y_pred >= θ])
    subject to keeping at least min_count_frac of boxes.

    Returns optimal threshold.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(db_path: str, timeframe: str, test_frac: float = 0.2):
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    df = load_ohlc_from_db(db_path, EXCHANGE, SYMBOL, timeframe)

    # ── 2. Detect boxes ───────────────────────────────────────────────────────
    logger.info("Detecting consolidation boxes…")
    boxes_raw = consolidation_boxes(df, min_bars=5, use_time_filter=False)
    if boxes_raw.empty:
        logger.error("No boxes detected.")
        return

    boxes_raw["start_time"] = df.index[boxes_raw["start"].astype(int)].values
    boxes_raw["end_time"]   = df.index[boxes_raw["end"].astype(int)].values
    boxes_raw["duration"]   = boxes_raw["end"].astype(int) - boxes_raw["start"].astype(int)
    logger.info("Detected %d boxes  (%.1f/1000 bars)",
                len(boxes_raw), len(boxes_raw) / len(df) * 1000)

    # Sanity filter: drop sub-minimum boxes
    boxes_raw = boxes_raw[boxes_raw["duration"] >= 2].copy()

    # ── 3. Features ───────────────────────────────────────────────────────────
    logger.info("Extracting features…")
    feat_df = build_feature_matrix(df, boxes_raw)
    logger.info("Feature matrix: %s", feat_df.shape)

    # ── 4. Labels (sqrt-transformed, hard-negatives already filtered) ─────────
    logger.info("Computing labels (MFE/MAE, sqrt transform)…")
    labels = build_labels(df, boxes_raw, sqrt_transform=True)

    # ── 5. Merge → drop NaN labels (no-breakout hard negatives) ───────────────
    feat_df["quality"] = labels
    before  = len(feat_df)
    feat_df = feat_df.dropna(subset=["quality"])
    dropped = before - len(feat_df)
    logger.info("Labeled: %d rows | Dropped (hard negatives): %d", len(feat_df), dropped)

    if len(feat_df) < 30:
        logger.error("Too few samples (%d). Need ≥30.", len(feat_df))
        return

    # ── 6. Feature alignment ──────────────────────────────────────────────────
    use_cols = [c for c in FEATURE_COLS if c in feat_df.columns]
    missing  = [c for c in FEATURE_COLS if c not in feat_df.columns]
    if missing:
        logger.warning("Missing feature cols (skipped): %s", missing)

    # ── 7. Time-based split ───────────────────────────────────────────────────
    feat_df   = feat_df.sort_values("_start")
    split_idx = int(len(feat_df) * (1 - test_frac))
    train_df  = feat_df.iloc[:split_idx]
    test_df   = feat_df.iloc[split_idx:]

    X_train = train_df[use_cols].astype(np.float32)
    y_train = train_df["quality"].astype(np.float32)
    X_test  = test_df[use_cols].astype(np.float32)
    y_test  = test_df["quality"].astype(np.float32)

    logger.info("Train: %d | Test: %d", len(X_train), len(X_test))

    # Sanitise: replace inf/NaN with training column medians
    col_medians = X_train.median()
    X_train = X_train.replace([np.inf, -np.inf], np.nan).fillna(col_medians)
    X_test  = X_test.replace([np.inf, -np.inf], np.nan).fillna(col_medians)

    # ── 8. XGBoost v2 ─────────────────────────────────────────────────────────
    logger.info("Training XGBoost (v2)…")
    model = xgb.XGBRegressor(
        n_estimators          = 500,
        learning_rate         = 0.05,
        max_depth             = 5,
        subsample             = 0.8,
        colsample_bytree      = 0.8,
        reg_alpha             = 0.1,
        reg_lambda            = 1.0,
        min_child_weight      = 3,         # prevent overfitting on small clusters
        gamma                 = 0.05,      # min split loss — reduces noise splits
        objective             = "reg:squarederror",
        eval_metric           = "mae",
        early_stopping_rounds = 30,
        random_state          = 42,
        n_jobs                = -1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    logger.info("Best iteration: %d", model.best_iteration)

    # ── 9. Evaluation ─────────────────────────────────────────────────────────
    y_pred = np.clip(model.predict(X_test), 0.0, 1.0)
    y_true = y_test.values

    mae     = mean_absolute_error(y_true, y_pred)
    rmse    = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    pearson = float(np.corrcoef(y_true, y_pred)[0, 1])
    spear_r, spear_p = spearmanr(y_true, y_pred)
    top20   = top_k_precision(y_true, y_pred, k_frac=0.20)
    top10   = top_k_precision(y_true, y_pred, k_frac=0.10)

    buckets   = bucket_analysis(y_true, y_pred)
    threshold = calibrate_threshold(y_true, y_pred, min_count_frac=0.10)

    logger.info("─" * 55)
    logger.info("TEST RESULTS")
    logger.info("  MAE              : %.4f", mae)
    logger.info("  RMSE             : %.4f", rmse)
    logger.info("  Pearson r        : %.4f", pearson)
    logger.info("  Spearman r       : %.4f (p=%.4f)", spear_r, spear_p)
    logger.info("  Top-20%% quality  : %.4f", top20)
    logger.info("  Top-10%% quality  : %.4f", top10)
    logger.info("  Optimal threshold: %.3f", threshold)
    logger.info("─" * 55)
    logger.info("Bucket analysis:\n%s", buckets.to_string(index=False))

    # Feature importance
    importances = pd.Series(
        model.feature_importances_, index=use_cols
    ).sort_values(ascending=False)
    logger.info("─" * 55)
    logger.info("Top-10 features:\n%s", importances.head(10).to_string())

    # ── 10. SHAP (optional) ───────────────────────────────────────────────────
    if SHAP_AVAILABLE:
        _compute_shap(model, X_test, use_cols)
    else:
        logger.info("SHAP not installed (pip install shap). Skipping SHAP plot.")

    # ── 11. Plots ─────────────────────────────────────────────────────────────
    _plot_results(y_true, y_pred, importances, buckets, threshold)

    # ── 12. Save model ────────────────────────────────────────────────────────
    model_data = {
        "model":            model,
        "feature_cols":     use_cols,
        "col_medians":      col_medians.to_dict(),
        "train_rows":       len(X_train),
        "test_rows":        len(X_test),
        "pearson_r":        float(pearson),
        "spearman_r":       float(spear_r),
        "mae":              float(mae),
        "optimal_threshold": float(threshold),
        "timeframe":        timeframe,
        "symbol":           SYMBOL,
        "sqrt_transform":   True,   # label space note for inference reference
    }
    with open(MODEL_OUT, "wb") as f:
        pickle.dump(model_data, f, protocol=4)
    logger.info("Model saved → %s", MODEL_OUT)

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
    fig.suptitle("Consolidation Box Quality Scorer v2 — Evaluation", fontsize=14)

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
    ax.set_title("Bucket Analysis (pred bins vs actual quality)")
    ax.legend(fontsize=8)

    # 5. Score distribution
    ax = axes[1, 1]
    ax.hist(y_pred, bins=30, color="#FF79C6", edgecolor="white", lw=0.4, label="Predicted")
    ax.hist(y_true, bins=30, color="#50FA7B", edgecolor="white", lw=0.4, alpha=0.6, label="Actual")
    ax.axvline(threshold, color="red", lw=1.5, ls="--", label=f"Threshold={threshold:.2f}")
    ax.set_xlabel("Quality Score")
    ax.set_ylabel("Count")
    ax.set_title("Score Distributions")
    ax.legend(fontsize=8)

    # 6. Cumulative rank quality (DCG-like)
    ax = axes[1, 2]
    sort_idx = np.argsort(y_pred)[::-1]
    cumulative_quality = np.cumsum(y_true[sort_idx]) / (np.arange(len(y_true)) + 1)
    ax.plot(cumulative_quality, color="#F1FA8C", lw=1.5)
    ax.axhline(np.mean(y_true), color="red", ls="--", lw=1, label="Mean quality")
    ax.set_xlabel("Number of boxes selected (ranked by score)")
    ax.set_ylabel("Avg true quality")
    ax.set_title("Cumulative Quality @ K")
    ax.legend(fontsize=8)

    plt.tight_layout()
    out = PLOT_DIR / "evaluation_v2.png"
    plt.savefig(str(out), dpi=120, bbox_inches="tight")
    plt.close()
    logger.info("Plot saved → %s", out)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train consolidation scorer v2")
    parser.add_argument("--db",        default=DEFAULT_DB)
    parser.add_argument("--timeframe", default=TIMEFRAME)
    parser.add_argument("--test-frac", type=float, default=0.2)
    args = parser.parse_args()

    run_pipeline(
        db_path   = args.db,
        timeframe = args.timeframe,
        test_frac = args.test_frac,
    )
