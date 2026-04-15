"""
features.py v2 — Extended feature extraction for consolidation box quality scoring.

All features computed using ONLY data available up to box.end (no leakage).

v2 additions:
  - ATR(14)-based normalization across all volatility features
  - Structural symmetry: top_touch_count, bot_touch_count, symmetry_score
  - Time-in-range: pct_time_near_top, pct_time_near_bottom
  - Breakout strength features (using data strictly before box.end)

Feature groups:
  1. Geometry        — shape and size of box (ATR-normalized)
  2. Volatility      — price compression relative to ATR
  3. Structure v2    — swings, touches, symmetry, time-in-range
  4. Context         — trend slope, rel position, vol compression
  5. Pre-box breakout strength (last N bars before box end)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# ATR helper
# ─────────────────────────────────────────────────────────────────────────────

def _compute_atr(df_slice: pd.DataFrame, period: int = 14) -> float:
    """
    Compute ATR(period) for the given slice.
    Returns scalar ATR value, or fallback to mean(high-low) if too few rows.
    """
    n = len(df_slice)
    if n < 2:
        hl = (df_slice["high"] - df_slice["low"]).mean()
        return float(hl) if hl > 0 else 1e-9

    hi  = df_slice["high"].to_numpy(dtype=np.float64)
    lo  = df_slice["low"].to_numpy(dtype=np.float64)
    cl  = df_slice["close"].to_numpy(dtype=np.float64)

    prev_close = cl[:-1]
    tr = np.maximum(
        hi[1:] - lo[1:],
        np.maximum(np.abs(hi[1:] - prev_close), np.abs(lo[1:] - prev_close))
    )
    # Use min(period, available bars) to avoid NaN
    window = min(period, len(tr))
    atr = float(np.mean(tr[-window:]))
    return max(atr, 1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers (unchanged from v1)
# ─────────────────────────────────────────────────────────────────────────────

def _candle_range(df_slice: pd.DataFrame) -> np.ndarray:
    return (df_slice["high"] - df_slice["low"]).to_numpy(dtype=np.float64)


def _body_size(df_slice: pd.DataFrame) -> np.ndarray:
    return np.abs(df_slice["close"] - df_slice["open"]).to_numpy(dtype=np.float64)


def _wick_total(df_slice: pd.DataFrame) -> np.ndarray:
    return _candle_range(df_slice) - _body_size(df_slice)


def _count_touches(prices: np.ndarray, level: float, tolerance_pct: float = 0.002) -> int:
    """Count bars whose price comes within tolerance% of a level."""
    tol = level * tolerance_pct
    return int(np.sum(np.abs(prices - level) <= tol))


def _pct_time_near(prices: np.ndarray, level: float, tolerance_pct: float = 0.003) -> float:
    """Fraction of bars within tolerance% of a boundary level."""
    if len(prices) == 0:
        return 0.0
    tol = level * tolerance_pct
    return float(np.mean(np.abs(prices - level) <= tol))


def _count_internal_swings(high_arr: np.ndarray, low_arr: np.ndarray) -> int:
    n = len(high_arr)
    if n < 3:
        return 0
    swings = 0
    for i in range(1, n - 1):
        if high_arr[i] > high_arr[i - 1] and high_arr[i] > high_arr[i + 1]:
            swings += 1
        if low_arr[i] < low_arr[i - 1] and low_arr[i] < low_arr[i + 1]:
            swings += 1
    return swings


def _linear_slope(prices: np.ndarray) -> float:
    if len(prices) < 2:
        return 0.0
    x = np.arange(len(prices), dtype=np.float64)
    slope = np.polyfit(x, prices, 1)[0]
    mean_p = np.mean(prices)
    return float(slope / mean_p) if mean_p != 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Main feature extractor
# ─────────────────────────────────────────────────────────────────────────────

def extract_features(df: pd.DataFrame, box: pd.Series) -> Optional[Dict[str, float]]:
    """
    Extract feature dict for one consolidation box.

    Parameters
    ----------
    df  : Full OHLC DataFrame.
    box : One row (start, end, top, bottom required).

    Returns None if box is invalid.
    """
    start  = int(box["start"])
    end    = int(box["end"])
    top    = float(box["top"])
    bottom = float(box["bottom"])
    duration = end - start

    if duration < 1 or start < 0 or end >= len(df):
        return None

    # Slices
    inside      = df.iloc[start: end + 1]
    pre_window  = max(0, start - 50)
    pre         = df.iloc[pre_window: start]
    # Last 20 bars before box (for pre-box context ATR)
    atr_window  = df.iloc[max(0, start - 20): start + 1]

    hi_in  = inside["high"].to_numpy(dtype=np.float64)
    lo_in  = inside["low"].to_numpy(dtype=np.float64)
    cl_in  = inside["close"].to_numpy(dtype=np.float64)
    op_in  = inside["open"].to_numpy(dtype=np.float64)
    rng_in = _candle_range(inside)
    body_in = _body_size(inside)
    wick_in = _wick_total(inside)

    box_height    = max(top - bottom, 1e-9)
    avg_range_in  = max(float(np.mean(rng_in)) if len(rng_in) > 0 else 1e-9, 1e-9)

    # ── ATR (14) computed on [pre ∪ inside] ───────────────────────────────────
    # Use last 14 bars available before / at box end — no leakage
    atr_slice = df.iloc[max(0, end - 28): end + 1]   # 2× window for stability
    atr       = _compute_atr(atr_slice, period=14)

    # ── 1. Box Geometry (ATR-normalized) ──────────────────────────────────────
    height_atr        = box_height / atr
    height_norm       = box_height / avg_range_in
    duration_raw      = float(duration)
    height_per_bar    = box_height / duration_raw

    # ── 2. Volatility (ATR-normalized) ────────────────────────────────────────
    close_std         = float(np.std(cl_in)) if len(cl_in) > 1 else 0.0
    close_std_atr     = close_std / atr            # regime-stable
    close_std_norm    = close_std / box_height     # relative to box size

    avg_candle_range  = avg_range_in
    avg_range_atr     = avg_candle_range / atr     # range vs ATR
    compression_atr   = box_height / (atr * duration_raw ** 0.5)  # volatility-adj squeeze

    range_std         = float(np.std(rng_in)) if len(rng_in) > 1 else 0.0
    range_cv          = range_std / avg_candle_range

    # ── 3. Structure v2 ───────────────────────────────────────────────────────
    n_swings          = _count_internal_swings(hi_in, lo_in)
    n_swings_norm     = n_swings / duration_raw

    # Touch counts using high/low arrays
    top_touches       = _count_touches(hi_in, top)
    bot_touches       = _count_touches(lo_in, bottom)
    touch_total       = max(top_touches + bot_touches, 1)

    # Symmetry: balanced touches → stronger zone
    symmetry_score    = min(top_touches, bot_touches) / max(max(top_touches, bot_touches), 1)

    # Time-in-range: fraction of bars near each boundary (liquidity buildup)
    pct_time_near_top = _pct_time_near(hi_in, top)
    pct_time_near_bot = _pct_time_near(lo_in, bottom)

    # Wick-to-body ratio
    mean_body         = float(np.mean(body_in)) if len(body_in) > 0 else 0.0
    mean_wick         = float(np.mean(wick_in)) if len(wick_in) > 0 else 0.0
    wick_body_ratio   = mean_wick / max(mean_body, 1e-9)

    # Pct of candles fully inside box
    fully_inside_mask = (
        (cl_in >= bottom) & (cl_in <= top) &
        (op_in >= bottom) & (op_in <= top)
    )
    pct_contained     = float(np.mean(fully_inside_mask))

    # Symmetry of price position inside box
    mid_price         = (top + bottom) / 2
    close_above_mid   = float(np.mean(cl_in > mid_price))

    # ── 4. Context before box ─────────────────────────────────────────────────
    if len(pre) >= 5:
        pre_closes       = pre["close"].to_numpy(dtype=np.float64)
        pre_highs        = pre["high"].to_numpy(dtype=np.float64)
        pre_lows         = pre["low"].to_numpy(dtype=np.float64)
        pre_ranges       = _candle_range(pre)

        trend_slope      = _linear_slope(pre_closes)
        avg_range_before = float(np.mean(pre_ranges))
        atr_ratio        = box_height / max(avg_range_before, 1e-9)       # box vs pre-range
        atr_ratio_true   = box_height / atr                                # box vs true ATR

        recent_high      = float(np.max(pre_highs[-20:])) if len(pre_highs) >= 20 else float(np.max(pre_highs))
        recent_low       = float(np.min(pre_lows[-20:]))  if len(pre_lows)  >= 20 else float(np.min(pre_lows))
        recent_range     = max(recent_high - recent_low, 1e-9)
        box_mid          = (top + bottom) / 2
        rel_pos          = (box_mid - recent_low) / recent_range

        pre_std          = float(np.std(pre_closes)) if len(pre_closes) > 1 else 1.0
        pre_vol_compression = box_height / max(pre_std, 1e-9)
    else:
        trend_slope         = 0.0
        atr_ratio           = 1.0
        atr_ratio_true      = box_height / atr
        rel_pos             = 0.5
        pre_vol_compression = 1.0

    # ── 5. Pre-breakout strength (last few bars inside box) ───────────────────
    # Use last min(5, duration) bars of the box as "breakout approach" features
    approach_n     = max(1, min(5, duration))
    approach_slice = inside.iloc[-approach_n:]

    ap_body   = _body_size(approach_slice)
    ap_range  = _candle_range(approach_slice)
    ap_cl     = approach_slice["close"].to_numpy(dtype=np.float64)
    ap_vol    = approach_slice["volume"].to_numpy(dtype=np.float64) if "volume" in approach_slice.columns else np.ones(approach_n)

    # Breakout candle body / box_height (momentum signal)
    approach_body_norm  = float(np.mean(ap_body))  / box_height
    # Breakout volume vs average box volume (if available)
    box_avg_vol         = float(inside["volume"].mean()) if "volume" in inside.columns else 1.0
    approach_vol_ratio  = float(np.mean(ap_vol)) / max(box_avg_vol, 1e-9)
    # Gap strength: distance of last close from nearer boundary
    last_close          = float(cl_in[-1])
    dist_to_top         = (top    - last_close) / box_height
    dist_to_bottom      = (last_close - bottom) / box_height
    boundary_proximity  = min(abs(dist_to_top), abs(dist_to_bottom))   # close to a wall = coiling

    return {
        # ── Geometry (ATR-normalized) ──────────────────────────────────────
        "height_atr":           height_atr,           # box height / ATR(14)
        "height_norm":          height_norm,           # box height / avg candle range
        "duration":             duration_raw,
        "height_per_bar":       height_per_bar,

        # ── Volatility (ATR-normalized) ────────────────────────────────────
        "close_std_atr":        close_std_atr,         # std(close) / ATR
        "close_std_norm":       close_std_norm,        # std(close) / box_height
        "avg_range_atr":        avg_range_atr,         # mean(H-L) / ATR
        "compression_atr":      compression_atr,       # volatility-adjusted squeeze
        "range_cv":             range_cv,              # candle size consistency

        # ── Structure v2 ───────────────────────────────────────────────────
        "n_swings_norm":        n_swings_norm,
        "top_touches":          float(top_touches),
        "bot_touches":          float(bot_touches),
        "symmetry_score":       symmetry_score,        # min/max(touches)
        "pct_time_near_top":    pct_time_near_top,
        "pct_time_near_bot":    pct_time_near_bot,
        "wick_body_ratio":      wick_body_ratio,
        "pct_contained":        pct_contained,
        "close_above_mid":      close_above_mid,

        # ── Context ────────────────────────────────────────────────────────
        "trend_slope":          trend_slope,
        "atr_ratio":            atr_ratio,
        "atr_ratio_true":       atr_ratio_true,        # box_height / true ATR(14)
        "rel_pos":              rel_pos,
        "pre_vol_compression":  pre_vol_compression,

        # ── Pre-breakout approach ──────────────────────────────────────────
        "approach_body_norm":   approach_body_norm,    # last-N body size / box_height
        "approach_vol_ratio":   approach_vol_ratio,    # last-N volume / avg box volume
        "boundary_proximity":   boundary_proximity,    # last close distance to nearest wall
    }


# ─────────────────────────────────────────────────────────────────────────────
# Batch extractor
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_matrix(df: pd.DataFrame, boxes: pd.DataFrame) -> pd.DataFrame:
    """Extract features for all boxes. Rows with None features are dropped."""
    records = []
    for idx, row in boxes.iterrows():
        feats = extract_features(df, row)
        if feats is not None:
            feats["_box_idx"] = idx
            feats["_start"]   = int(row["start"])
            feats["_end"]     = int(row["end"])
            records.append(feats)

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).set_index("_box_idx")
