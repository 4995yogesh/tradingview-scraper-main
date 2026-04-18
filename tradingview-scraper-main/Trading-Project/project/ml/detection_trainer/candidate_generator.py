"""
candidate_generator.py — Sliding-window consolidation candidate generator.

Approach:
  1. Slide fixed windows (5, 10, 15, 20, 30 candles) across the chart
  2. Volatility filter: range < 1.5 × ATR14 (pre-window)
  3. NMS (Non-Max Suppression) via IoU > 0.5 to de-duplicate overlapping boxes
  4. Returns list of candidate dicts compatible with detection_features.py

No future data used — all features derived from the window and its pre-history.
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Candidate window lengths in candles
WINDOW_SIZES = [5, 10, 15, 20, 30]

# Box must be narrower than this × ATR to qualify
RANGE_ATR_THRESHOLD = 1.5

# Minimum bars of pre-history required before a window
MIN_PRE_BARS = 14

# NMS overlap threshold (IoU on price axis)
NMS_IOU_THRESHOLD = 0.5


# ── Price-axis IoU ─────────────────────────────────────────────────────────────

def _price_iou(a: Dict, b: Dict) -> float:
    """
    Intersection-over-Union on the price axis only.
    We ignore time axis for NMS — boxes at same price range but different times
    are NOT suppressed (they are separate zones).
    For temporal NMS we compare both axes.
    """
    a_lo, a_hi = a["price_low"],  a["price_high"]
    b_lo, b_hi = b["price_low"],  b["price_high"]

    inter_lo = max(a_lo, b_lo)
    inter_hi = min(a_hi, b_hi)
    if inter_hi <= inter_lo:
        return 0.0

    inter  = inter_hi - inter_lo
    union  = max(a_hi, b_hi) - min(a_lo, b_lo)
    return inter / union if union > 1e-12 else 0.0


def _temporal_overlap(a: Dict, b: Dict) -> float:
    """Fraction of temporal overlap between two boxes."""
    a_s, a_e = a["start"], a["end"]
    b_s, b_e = b["start"], b["end"]
    inter_s = max(a_s, b_s)
    inter_e = min(a_e, b_e)
    if inter_e <= inter_s:
        return 0.0
    inter = inter_e - inter_s + 1
    union = max(a_e, b_e) - min(a_s, b_s) + 1
    return inter / union if union > 0 else 0.0


def _combined_iou(a: Dict, b: Dict) -> float:
    """Combined IoU = mean of price IoU and temporal overlap."""
    return (_price_iou(a, b) + _temporal_overlap(a, b)) / 2.0


# ── Non-Max Suppression ────────────────────────────────────────────────────────

def nms(
    candidates: List[Dict],
    score_key: str = "detection_score",
    iou_threshold: float = NMS_IOU_THRESHOLD,
) -> List[Dict]:
    """
    Suppress overlapping candidates, keeping highest score.
    Input list must have `score_key`, `price_high`, `price_low`, `start`, `end`.
    Candidates without a score are treated as score=0.
    """
    if not candidates:
        return []

    # Sort descending by score
    sorted_cands = sorted(candidates, key=lambda c: c.get(score_key, 0.0), reverse=True)
    kept: List[Dict] = []

    for cand in sorted_cands:
        suppressed = False
        for keep in kept:
            if _combined_iou(cand, keep) > iou_threshold:
                suppressed = True
                break
        if not suppressed:
            kept.append(cand)

    logger.debug("NMS: %d → %d candidates (threshold=%.2f)", len(candidates), len(kept), iou_threshold)
    return kept


# ── ATR helper ────────────────────────────────────────────────────────────────

def _atr14(df_slice: pd.DataFrame) -> float:
    n = len(df_slice)
    if n < 2:
        hl = float((df_slice["high"] - df_slice["low"]).mean())
        return max(hl, 1e-9)
    hi  = df_slice["high"].to_numpy(dtype=np.float64)
    lo  = df_slice["low"].to_numpy(dtype=np.float64)
    cl  = df_slice["close"].to_numpy(dtype=np.float64)
    prev = cl[:-1]
    tr  = np.maximum(hi[1:] - lo[1:],
          np.maximum(np.abs(hi[1:] - prev), np.abs(lo[1:] - prev)))
    w = min(14, len(tr))
    return max(float(np.mean(tr[-w:])), 1e-9)


# ── Main generator ────────────────────────────────────────────────────────────

def generate_candidates(df: pd.DataFrame) -> List[Dict]:
    """
    Slide variable-length windows across `df` and return a list of candidate
    consolidation boxes that pass the volatility filter.

    Each candidate dict contains:
        start, end          — integer indices into df
        price_high          — float
        price_low           — float
        duration_bars       — int
        range_norm          — float  (range / pre-ATR)

    Scoring (detection_score) is NOT set here — caller should run
    DetectionScorer.score_candidates() on the result.
    """
    if df is None or len(df) < max(WINDOW_SIZES) + MIN_PRE_BARS:
        logger.warning("generate_candidates: insufficient data (%d bars)", len(df) if df is not None else 0)
        return []

    n = len(df)
    candidates: List[Dict] = []

    hi_arr = df["high"].to_numpy(dtype=np.float64)
    lo_arr = df["low"].to_numpy(dtype=np.float64)

    for window in WINDOW_SIZES:
        for start in range(MIN_PRE_BARS, n - window):
            end = start + window - 1
            if end >= n:
                break

            # Volatility filter: box range vs pre-window ATR
            pre_slice  = df.iloc[max(0, start - 14) : start]
            pre_atr    = _atr14(pre_slice)

            box_high = float(np.max(hi_arr[start : end + 1]))
            box_low  = float(np.min(lo_arr[start : end + 1]))
            box_range = box_high - box_low

            if box_range > RANGE_ATR_THRESHOLD * pre_atr:
                continue  # too wide — not a consolidation

            candidates.append({
                "start":      start,
                "end":        end,
                "price_high": box_high,
                "price_low":  box_low,
                "duration_bars": window,
                "range_norm": box_range / pre_atr,
            })

    logger.info(
        "generate_candidates: %d raw candidates from %d bars (windows=%s)",
        len(candidates), n, WINDOW_SIZES,
    )
    return candidates
