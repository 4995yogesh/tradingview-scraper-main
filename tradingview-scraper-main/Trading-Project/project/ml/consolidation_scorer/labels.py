"""
labels.py — Improved label generation with MFE/MAE path quality.

Labeling contract (zero data leakage):
  Features → df.iloc[0 : box.end+1]   (past only)
  Labels   → df.iloc[box.end+1 : ...]  (future only)

Label logic v2:
  1. Adaptive lookforward: min(50, max(10, 2 × duration))
  2. Find breakout direction (first close outside box)
  3. Track MFE (max favorable excursion) and MAE (max adverse excursion)
     along the breakout path
  4. quality = (MFE / box_height) - (MAE / box_height × penalty_factor)
  5. Fakeout penalty ×0.3 if re-entry within N bars
  6. Hard-negative filter: return None if no breakout occurs
  7. sqrt transform before returning (caller decides whether to apply)
  8. Clip to [0, 1]
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Tunable parameters
# ─────────────────────────────────────────────────────────────────────────────
PENALTY_FACTOR        = 0.5    # MAE weight — softened from 0.6
FAKEOUT_MULT          = 0.4    # quality multiplier on fakeout — softened from 0.3
MIN_BOX_HEIGHT        = 1e-5   # below this → noise, reject
SQRT_TRANSFORM        = True   # apply sqrt to stabilise target variance
MFE_CAP_MULTIPLES     = 2.0    # cap MFE at 2× box height (was 5×) → better score spread
FAKEOUT_MIN_BARS      = 2      # fakeout requires re-entry for at least N bars (not just a wick)


# ─────────────────────────────────────────────────────────────────────────────
# Core label function
# ─────────────────────────────────────────────────────────────────────────────

def compute_label(
    df: pd.DataFrame,
    box: pd.Series,
    lookforward_cap:   int   = 100,
    lookforward_min:   int   = 20,
) -> Optional[float]:
    """
    Compute y_new for structural upgrade.
    1.0 = SUCCESS (breakout + follow-through >= 1.5 * box_height or 1.5 * ATR)
    0.0 = FAILURE (fakeout or reversal < 10 bars)
    None = Ambiguous / No breakout
    """
    start    = int(box["start"])
    end      = int(box["end"])
    top      = float(box["top"])
    bottom   = float(box["bottom"])
    box_height = max(top - bottom, 1e-9)

    # Future window
    future_start = end + 1
    # Use 50 bars for follow-through check
    future_end = min(len(df), future_start + 50)
    if future_start >= len(df): return None
    
    future = df.iloc[future_start:future_end]
    if len(future) < 5: return None
    
    fc = future["close"].to_numpy()
    fh = future["high"].to_numpy()
    fl = future["low"].to_numpy()
    
    # breakout detection
    direction = 0
    breakout_idx = -1
    for i, c in enumerate(fc):
        if c > top: direction = 1; breakout_idx = i; break
        if c < bottom: direction = -1; breakout_idx = i; break
        
    if direction == 0: return None
    
    # follow-through check
    post_brk = fc[breakout_idx:]
    post_h = fh[breakout_idx:]
    post_l = fl[breakout_idx:]
    
    # ATR for scaling if box is too tight
    atr_slice = df.iloc[max(0, end-14):end+1]
    atr = (atr_slice["high"] - atr_slice["low"]).mean()
    success_dist = max(box_height * 1.5, atr * 1.5)
    
    # Failure check (first 10 bars after breakout)
    fail_window = 10
    recent_post = fc[breakout_idx : breakout_idx + fail_window]
    
    if direction == 1:
        # Reversal failure: price closes back below bottom of box or stays below top for too long
        reversal = np.any(recent_post < bottom)
        fakeout = np.any(recent_post < top) and (len(recent_post) >= 5 and np.mean(recent_post < top) > 0.6)
        
        if reversal or fakeout: return 0.0
        
        mfe = np.max(post_h) - top
        if mfe >= success_dist: return 1.0
        
    else: # bearish
        reversal = np.any(recent_post > top)
        fakeout = np.any(recent_post > bottom) and (len(recent_post) >= 5 and np.mean(recent_post > bottom) > 0.6)
        
        if reversal or fakeout: return 0.0
        
        mfe = bottom - np.min(post_l)
        if mfe >= success_dist: return 1.0
        
    return None # Ambiguous (neither success nor quick failure)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _max_consecutive(mask: np.ndarray) -> int:
    """Return the maximum number of consecutive True values in a boolean array."""
    max_run = 0
    run = 0
    for v in mask:
        if v:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run


# ─────────────────────────────────────────────────────────────────────────────
# Batch label generation
# ─────────────────────────────────────────────────────────────────────────────

def build_labels(
    df: pd.DataFrame,
    boxes: pd.DataFrame,
    lookforward_cap:   int   = 100,
    lookforward_min:   int   = 20,
    verbose:           bool  = True,
) -> pd.Series:
    """
    Compute quality labels for all boxes using structural success/failure logic.
    None values → NaN → dropped in training pipeline.
    """
    labels = {}
    for idx, row in boxes.iterrows():
        score = compute_label(
            df, row,
            lookforward_cap = lookforward_cap,
            lookforward_min = lookforward_min,
        )
        labels[idx] = score   # None becomes NaN after Series construction

    series = pd.Series(labels, name="quality_label")

    if verbose:
        valid = series.dropna()
        if len(valid) > 0:
            import logging
            _log = logging.getLogger(__name__)
            counts = valid.value_counts().to_dict()
            _log.info("Label counts: %s", str(counts))

    return series

