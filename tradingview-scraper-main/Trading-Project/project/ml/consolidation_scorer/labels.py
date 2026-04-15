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
    lookforward_cap:   int   = 100,   # raised: gives boxes more room to develop
    lookforward_min:   int   = 10,
    penalty_factor:    float = PENALTY_FACTOR,
    sqrt_transform:    bool  = SQRT_TRANSFORM,
    mfe_cap_multiples: float = MFE_CAP_MULTIPLES,
    fakeout_min_bars:  int   = FAKEOUT_MIN_BARS,
) -> Optional[float]:
    """
    Compute quality label for one consolidation box using MFE/MAE path quality.

    Returns float in [0, 1], or None if box should be hard-filtered out.
    """
    start    = int(box["start"])
    end      = int(box["end"])
    top      = float(box["top"])
    bottom   = float(box["bottom"])
    duration = end - start

    box_height = top - bottom

    # ── Hard negative filters ─────────────────────────────────────────────────
    if box_height < MIN_BOX_HEIGHT:
        return None                          # noise box
    if duration < 2:
        return None                          # degenerate box

    # ── Adaptive lookforward ──────────────────────────────────────────────────
    lookforward = min(lookforward_cap, max(lookforward_min, 2 * duration))

    future_start = end + 1
    future_end   = future_start + lookforward

    if future_start >= len(df):
        return None    # no future data → unlabeled (hard filter)

    future = df.iloc[future_start: min(future_end, len(df))]
    if len(future) < 2:
        return None

    future_close  = future["close"].to_numpy(dtype=np.float64)
    future_high   = future["high"].to_numpy(dtype=np.float64)
    future_low    = future["low"].to_numpy(dtype=np.float64)

    # ── Step 1: Find breakout direction ───────────────────────────────────────
    direction    = None
    breakout_bar = None
    for i, c in enumerate(future_close):
        if c > top:
            direction    = "up"
            breakout_bar = i
            break
        elif c < bottom:
            direction    = "down"
            breakout_bar = i
            break

    # Hard filter: no breakout → discard (avoids noisy 0.05 labels)
    if direction is None:
        return None

    # ── Step 2: Track MFE and MAE along breakout path ────────────────────────
    post_high  = future_high[breakout_bar:]
    post_low   = future_low[breakout_bar:]
    post_close = future_close[breakout_bar:]

    if direction == "up":
        # Favorable: how far above top did price reach
        # Adverse:   how far below top did price drop (pullback)
        mfe = max(float(np.max(post_high)) - top, 0.0)
        mae = max(top - float(np.min(post_low)), 0.0)
    else:  # down
        mfe = max(bottom - float(np.min(post_low)), 0.0)
        mae = max(float(np.max(post_high)) - bottom, 0.0)

    # ── Step 3: Path quality with MFE/MAE ────────────────────────────────────
    # Cap at mfe_cap_multiples× box height.
    # Using 2× (not 5×) ensures a 2× extension = perfect score = 1.0
    # giving good spread across the full [0, 1] range.
    cap = mfe_cap_multiples
    mfe_norm = min(mfe / box_height, cap) / cap            # → [0, 1]
    mae_norm = min(mae / box_height, cap) / cap            # → [0, 1]

    raw_quality = mfe_norm - mae_norm * penalty_factor
    raw_quality = max(raw_quality, 0.0)                    # floor at 0

    # ── Step 4: Fakeout detection ─────────────────────────────────────────────
    # Require re-entry sustained for fakeout_min_bars consecutive bars
    # (not just a single wick) to avoid over-penalising normal pullbacks.
    fakeout_window = max(3, duration // 2)
    fk_close = post_close[:fakeout_window]

    is_fakeout = False
    if direction == "up":
        re_entries = fk_close < top
        # Count consecutive runs of re-entry
        max_consec = _max_consecutive(re_entries)
        is_fakeout = max_consec >= fakeout_min_bars
    elif direction == "down":
        re_entries = fk_close > bottom
        max_consec = _max_consecutive(re_entries)
        is_fakeout = max_consec >= fakeout_min_bars

    if is_fakeout:
        raw_quality *= FAKEOUT_MULT

    # ── Step 5: Optional sqrt transform ──────────────────────────────────────
    if sqrt_transform:
        raw_quality = float(np.sqrt(raw_quality))

    return float(np.clip(raw_quality, 0.0, 1.0))


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
    lookforward_min:   int   = 10,
    penalty_factor:    float = PENALTY_FACTOR,
    sqrt_transform:    bool  = SQRT_TRANSFORM,
    verbose:           bool  = True,
) -> pd.Series:
    """
    Compute quality labels for all boxes.

    Returns pd.Series (indexed by boxes.index).
    None values → NaN → dropped in training pipeline.
    """
    labels = {}
    for idx, row in boxes.iterrows():
        score = compute_label(
            df, row,
            lookforward_cap = lookforward_cap,
            lookforward_min = lookforward_min,
            penalty_factor  = penalty_factor,
            sqrt_transform  = sqrt_transform,
        )
        labels[idx] = score   # None becomes NaN after Series construction

    series = pd.Series(labels, name="quality_label")

    if verbose:
        valid = series.dropna()
        if len(valid) > 0:
            import logging
            _log = logging.getLogger(__name__)
            _log.info(
                "Label distribution (n=%d): min=%.3f q25=%.3f median=%.3f q75=%.3f max=%.3f std=%.3f",
                len(valid),
                float(valid.min()), float(valid.quantile(0.25)),
                float(valid.median()), float(valid.quantile(0.75)),
                float(valid.max()), float(valid.std()),
            )

    return series

