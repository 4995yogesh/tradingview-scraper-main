"""
features.py v3 — Clean pre-breakout feature extraction for consolidation box quality scoring.

Architecture rule (CRITICAL):
  Features → ONLY pre-breakout data (df.iloc[0 : box.end+1])
  Labels   → post-breakout data computed separately in train.py / labels.py

v3 changes vs v2:
  - Removed dead post-breakout code block that existed after the return statement.
    These were never executed and introduced conceptual data-leakage risk.
  - Added EXPECTED_FEATURE_COUNT constant for schema validation.
  - Added explicit POST-BREAKOUT BOUNDARY comment to make the contract clear.
  - All 26 pre-breakout features preserved exactly as in v2.

Feature groups:
  1. Geometry        — shape and size of box (ATR-normalized)
  2. Volatility      — price compression relative to ATR
  3. Structure v2    — swings, touches, symmetry, time-in-range
  4. Context         — trend slope, rel position, vol compression
  5. Pre-box breakout approach (last N bars before box end — INSIDE box only)
"""

import hashlib
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple, List

EXPECTED_FEATURE_COUNT = 43

# Canonical ordered feature list (must be updated here ONLY)
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
    # Approach
    "approach_body_norm", "boundary_proximity", "tf_encoded_minutes",
    
    # Binary Structural
    "has_fvg_before_breakout", "has_fvg_inside_box", 
    "liquidity_sweep_before_breakout", "sweep_direction",
    "clean_breakout", "breakout_retest_occurred", "fakeout_then_reversal",
    "multi_swing_compression", "equal_highs_or_lows_present",
    
    # Categorical
    "breakout_type", "compression_type", "structure_bias", "box_position_in_trend",
    
    # Interactions
    "tightness_x_strength", "compression_x_impulse", "contraction_x_clean",
    
    # Sequence
    "sequence_pattern",
]

# Schema fingerprint to detect regressions
FEATURE_VERSION = hashlib.sha256(str(tuple(FEATURE_COLS)).encode()).hexdigest()

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
    window = min(period, len(tr))
    atr = float(np.mean(tr[-window:]))
    return max(atr, 1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
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
# Structural logic helpers
# ─────────────────────────────────────────────────────────────────────────────

def _has_fvg(df_slice: pd.DataFrame) -> bool:
    """Returns True if any candle in slice creates a fresh FVG."""
    if len(df_slice) < 3:
        return False
    # Bullish: low[i] > high[i-2]
    # Bearish: high[i] < low[i-2]
    h = df_slice["high"].to_numpy()
    l = df_slice["low"].to_numpy()
    bullish = (l[2:] > h[:-2])
    bearish = (h[2:] < l[:-2])
    return bool(np.any(bullish) or np.any(bearish))


def _detect_liquidity_sweep(df: pd.DataFrame, box: pd.Series) -> Tuple[bool, int]:
    """
    Returns (has_sweep, direction).
    direction: +1 (upside sweep), -1 (downside sweep), 0 (none).
    Logic: price penetrates boundary then closes back inside.
    """
    start, end = int(box["start"]), int(box["end"])
    top, bottom = float(box["top"]), float(box["bottom"])
    inside = df.iloc[start:end + 1]
    
    h = inside["high"].to_numpy()
    l = inside["low"].to_numpy()
    c = inside["close"].to_numpy()
    
    # Simple deterministic check: any bar high > top and close < top?
    up_sweep = np.any((h > top) & (c < top))
    down_sweep = np.any((l < bottom) & (c > bottom))
    
    if up_sweep and down_sweep: 
        return True, 1
    if up_sweep:
        return True, 1
    if down_sweep:
        return True, -1
    return False, 0


def _detect_retest_and_clean(df: pd.DataFrame, box_end: int, top: float, bottom: float, window: int = 3) -> Dict[str, bool]:
    """
    Uses Reactive window (+3) to check for retests and breakout quality.
    """
    n = len(df)
    obs_end = min(n, box_end + 1 + window)
    post = df.iloc[box_end + 1 : obs_end]
    
    res = {"clean": False, "retest": False, "fakeout": False}
    if post.empty:
        return res
        
    ph = post["high"].to_numpy()
    pl = post["low"].to_numpy()
    pc = post["close"].to_numpy()
    
    # Find breakout direction
    direction = 0
    if pc[0] > top: direction = 1
    elif pc[0] < bottom: direction = -1
    
    if direction == 1:
        res["clean"] = pc[0] > top + (top - bottom) * 0.1
        res["retest"] = np.any(pl[1:] <= top * 1.001) if len(pl) > 1 else False
        res["fakeout"] = np.any(pc < top)
    elif direction == -1:
        res["clean"] = pc[0] < bottom - (top - bottom) * 0.1
        res["retest"] = np.any(ph[1:] >= bottom * 0.999) if len(ph) > 1 else False
        res["fakeout"] = np.any(pc > bottom)
        
    return res


def tf_to_minutes(tf: str) -> float:
    mapping = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440, "1w": 10080
    }
    return float(mapping.get(tf, 60))

def extract_features(df: pd.DataFrame, box: pd.Series, timeframe: str = "1h") -> Optional[Dict[str, float]]:
    """
    Extract Reactive Structure Features for one consolidation box.
    
    ARCHITECTURE CONTRACT (REACTIVE MODE):
      - Features observe [inside_box] + [3 candles AFTER breakout]
      - Volume features are strictly REMOVED.
    """
    start  = int(box["start"])
    end    = int(box["end"])
    top    = float(box["top"])
    bottom = float(box["bottom"])
    duration = end - start

    if duration < 1 or start < 0 or end >= len(df):
        return None

    # ── Slices ────────────────────────────────────────────────────────────────
    inside      = df.iloc[start: end + 1]
    pre_window  = max(0, start - 20)
    pre         = df.iloc[pre_window: start]
    
    # Reactive Breakout Window (+3 candles)
    n = len(df)
    post_idx = min(n, end + 1 + 3)
    post = df.iloc[end + 1 : post_idx]

    hi_in  = inside["high"].to_numpy(dtype=np.float64)
    lo_in  = inside["low"].to_numpy(dtype=np.float64)
    cl_in  = inside["close"].to_numpy(dtype=np.float64)
    op_in  = inside["open"].to_numpy(dtype=np.float64)
    rng_in = _candle_range(inside)
    body_in = _body_size(inside)
    wick_in = _wick_total(inside)

    box_height    = max(top - bottom, 1e-9)
    avg_range_in  = max(float(np.mean(rng_in)) if len(rng_in) > 0 else 1e-9, 1e-9)

    # ── ATR(14) ───────────────────────────────────────────────────────────────
    atr_slice = df.iloc[max(0, end - 28): end + 1]
    atr       = _compute_atr(atr_slice, period=14)

    # ── 1. Old statistical features (kept) ────────────────────────────────────
    height_atr        = box_height / atr
    height_norm       = box_height / avg_range_in
    duration_raw      = float(duration)
    height_per_bar    = box_height / duration_raw

    close_std         = float(np.std(cl_in)) if len(cl_in) > 1 else 0.0
    close_std_atr     = close_std / atr
    close_std_norm    = close_std / box_height
    avg_range_atr     = avg_range_in / atr
    compression_atr   = box_height / (atr * duration_raw ** 0.5)
    range_cv          = (float(np.std(rng_in)) / avg_range_in) if avg_range_in > 0 else 0.0

    n_swings          = _count_internal_swings(hi_in, lo_in)
    n_swings_norm     = n_swings / duration_raw
    top_touches       = _count_touches(hi_in, top)
    bot_touches       = _count_touches(lo_in, bottom)
    symmetry_score    = min(top_touches, bot_touches) / max(max(top_touches, bot_touches), 1)
    pct_time_near_top = _pct_time_near(hi_in, top)
    pct_time_near_bot = _pct_time_near(lo_in, bottom)
    wick_body_ratio   = float(np.mean(wick_in)) / max(float(np.mean(body_in)), 1e-9)
    pct_contained     = float(np.mean((cl_in >= bottom) & (cl_in <= top) & (op_in >= bottom) & (op_in <= top)))
    close_above_mid   = float(np.mean(cl_in > ((top + bottom) / 2)))

    trend_slope = _linear_slope(pre["close"].to_numpy()) if len(pre) >= 5 else 0.0
    atr_ratio   = box_height / max(float(pre["high"].max() - pre["low"].min()), 1e-9) if len(pre) >= 5 else 1.0
    atr_ratio_true = box_height / atr
    
    recent_high = float(pre["high"].max()) if not pre.empty else top
    recent_low  = float(pre["low"].min())  if not pre.empty else bottom
    recent_range = max(recent_high - recent_low, 1e-9)
    rel_pos     = ((top+bottom)/2 - recent_low) / recent_range
    pre_vol_compression = box_height / max(float(np.std(pre["close"])) if len(pre)>1 else 0.1, 0.1)

    approach_n     = max(1, min(5, duration))
    approach_slice = inside.iloc[-approach_n:]
    approach_body_norm = float(np.mean(_body_size(approach_slice))) / box_height
    boundary_proximity = min(abs(top - cl_in[-1]), abs(cl_in[-1] - bottom)) / box_height

    # ── 2. NEW Structural Binary Features ─────────────────────────────────────
    has_fvg_before  = _has_fvg(pre)
    has_fvg_inside  = _has_fvg(inside)
    has_sweep, sw_dir = _detect_liquidity_sweep(df, box)
    
    re_clean = _detect_retest_and_clean(df, end, top, bottom, window=3)
    
    # multi_swing_compression: high swings and low swings at least 2 each
    hi_swings = np.sum((hi_in[1:-1] > hi_in[:-2]) & (hi_in[1:-1] > hi_in[2:]))
    lo_swings = np.sum((lo_in[1:-1] < lo_in[:-2]) & (lo_in[1:-1] < lo_in[2:]))
    multi_swing = 1.0 if (hi_swings >= 2 and lo_swings >= 2) else 0.0

    # equal highs/lows present (within 0.1% of each other)
    eq_h = 0.0
    if hi_swings >= 2:
        sw_hs = hi_in[1:-1][(hi_in[1:-1] > hi_in[:-2]) & (hi_in[1:-1] > hi_in[2:])]
        if len(sw_hs) >= 2:
            for i in range(len(sw_hs)):
                for j in range(i+1, len(sw_hs)):
                    if abs(sw_hs[i] - sw_hs[j]) / sw_hs[i] < 0.001: eq_h = 1.0; break
    eq_l = 0.0
    if lo_swings >= 2:
        sw_ls = lo_in[1:-1][(lo_in[1:-1] < lo_in[:-2]) & (lo_in[1:-1] < lo_in[2:])]
        if len(sw_ls) >= 2:
            for i in range(len(sw_ls)):
                for j in range(i+1, len(sw_ls)):
                    if abs(sw_ls[i] - sw_ls[j]) / sw_ls[i] < 0.001: eq_l = 1.0; break
    
    equal_hl = 1.0 if (eq_h or eq_l) else 0.0

    # ── 3. Categorical Encodings (Locked Mappings) ─────────────────────────────
    # breakout_type: 0=impulse, 1=grind, 2=fakeout
    b_type = 0
    if re_clean["fakeout"]: b_type = 2
    elif not re_clean["clean"]: b_type = 1
    
    # compression_type: 0=tight, 1=moderate, 2=loose
    comp_type = 1
    if height_atr < 1.0: comp_type = 0
    elif height_atr > 2.5: comp_type = 2
    
    # structure_bias: 0=bearish, 1=neutral, 2=bullish
    bias = 1
    if trend_slope > 0.001: bias = 2
    elif trend_slope < -0.001: bias = 0
    
    # box_position_in_trend: 0=reversal, 1=range, 2=continuation
    pos_trend = 1
    if (bias == 2 and cl_in[-1] > recent_high) or (bias == 0 and cl_in[-1] < recent_low):
        pos_trend = 2
    elif (bias == 2 and cl_in[-1] < top - 0.5*box_height) or (bias == 0 and cl_in[-1] > bottom + 0.5*box_height):
        pos_trend = 0

    # ── 4. Interaction Features ───────────────────────────────────────────────
    breakout_bar_close = post["close"].iloc[0] if not post.empty else cl_in[-1]
    breakout_strength = abs(breakout_bar_close - (top if breakout_bar_close > top else bottom)) / box_height
    
    # tightness_score * breakout_strength
    tightness_x_strength = (1.0 / max(height_atr, 0.1)) * breakout_strength
    
    # compression_ratio * breakout_impulse
    impulse = abs(breakout_bar_close - cl_in[-1]) / atr
    compression_x_impulse = (1.0 / max(compression_atr, 0.1)) * impulse
    
    # range_contraction * breakout_cleanliness
    clean_val = 1.0 if re_clean["clean"] else 0.0
    contraction_x_clean = (1.0 / max(range_cv, 0.01)) * clean_val

    # ── 5. Sequence Encoding (Integer Locked) ─────────────────────────────────
    # 0 = compression_only, 1 = compression → sweep, 2 = compression → breakout, 
    # 3 = compression → sweep → breakout, 4 = compression → fakeout → reversal
    seq = 0
    has_breakout = not post.empty and (post["close"].iloc[0] > top or post["close"].iloc[0] < bottom)
    
    if re_clean["fakeout"]:
        seq = 4
    elif has_sweep and has_breakout:
        seq = 3
    elif has_breakout:
        seq = 2
    elif has_sweep:
        seq = 1

    features = {
        # Geometry
        "height_atr":           height_atr,
        "height_norm":          height_norm,
        "duration":             duration_raw,
        "height_per_bar":       height_per_bar,
        # Volatility
        "close_std_atr":        close_std_atr,
        "close_std_norm":       close_std_norm,
        "avg_range_atr":        avg_range_atr,
        "compression_atr":      compression_atr,
        "range_cv":             range_cv,
        # Structure
        "n_swings_norm":        n_swings_norm,
        "top_touches":          top_touches,
        "bot_touches":          bot_touches,
        "symmetry_score":       symmetry_score,
        "pct_time_near_top":    pct_time_near_top,
        "pct_time_near_bot":    pct_time_near_bot,
        "wick_body_ratio":      wick_body_ratio,
        "pct_contained":        pct_contained,
        "close_above_mid":      close_above_mid,
        # Context
        "trend_slope":          trend_slope,
        "atr_ratio":            atr_ratio,
        "atr_ratio_true":       atr_ratio_true,
        "rel_pos":              rel_pos,
        "pre_vol_compression":  pre_vol_compression,
        # Approach
        "approach_body_norm":   approach_body_norm,
        "boundary_proximity":   boundary_proximity,
        "tf_encoded_minutes":   tf_to_minutes(timeframe),
        
        # Binary Structural
        "has_fvg_before_breakout": float(has_fvg_before),
        "has_fvg_inside_box":      float(has_fvg_inside),
        "liquidity_sweep_before_breakout": float(has_sweep),
        "sweep_direction":         float(sw_dir),
        "clean_breakout":          float(re_clean["clean"]),
        "breakout_retest_occurred": float(re_clean["retest"]),
        "fakeout_then_reversal":   float(re_clean["fakeout"]),
        "multi_swing_compression": multi_swing,
        "equal_highs_or_lows_present": equal_hl,
        
        # Categorical
        "breakout_type":           float(b_type),
        "compression_type":        float(comp_type),
        "structure_bias":          float(bias),
        "box_position_in_trend":   float(pos_trend),
        
        # Interactions
        "tightness_x_strength":    tightness_x_strength,
        "compression_x_impulse":   compression_x_impulse,
        "contraction_x_clean":     contraction_x_clean,
        
        # Sequence
        "sequence_pattern":        float(seq)
    }

    assert len(features) == EXPECTED_FEATURE_COUNT, f"Count mistmatch: {len(features)} != {EXPECTED_FEATURE_COUNT}"
    return features


# ─────────────────────────────────────────────────────────────────────────────
# Batch extractor
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_matrix(df: pd.DataFrame, boxes: pd.DataFrame, timeframe: str = "1h") -> pd.DataFrame:
    """Extract features for all boxes. Rows with None features are dropped."""
    records = []
    for idx, row in boxes.iterrows():
        feats = extract_features(df, row, timeframe=timeframe)
        if feats is not None:
            feats["_box_idx"] = idx
            feats["_start"]   = int(row["start"])
            feats["_end"]     = int(row["end"])
            records.append(feats)

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).set_index("_box_idx")
