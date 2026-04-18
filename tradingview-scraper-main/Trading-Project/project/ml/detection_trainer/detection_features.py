"""
detection_features.py  — Pre-box feature extraction for detection model.

CONTRACT: ONLY pre-box data (df.iloc[0:end]) may be used.
          Never touch post-box candles.

Features (10 total):
  1. duration_bars         — box length in candles
  2. range_norm            — (high-low) / ATR14  (ATR computed pre-box)
  3. volatility_compression— box ATR / pre-box ATR (values <1 = compression)
  4. avg_candle_size       — mean(high-low) inside box, ATR-normalized
  5. wick_ratio            — mean(upper+lower wick) / mean(range) inside box
  6. top_touches           — bars closing within 10% of range from top
  7. bot_touches           — bars closing within 10% of range from bottom
  8. pre_trend_slope       — linear slope of close over 20 pre-box bars, ATR-norm
  9. impulse_dist          — distance to closest prior swing high/low, ATR-norm
 10. time_in_range_pct     — % bars where close stays inside [low, high] of box
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

EXPECTED_FEATURE_COUNT = 10

# Columns that would cause lookahead — banned from feature dict
_LEAKAGE_KEYS = frozenset({
    "breakout_direction", "mfe", "mae", "future_return",
    "post_box_high", "post_box_low",
})


# ── ATR helper ────────────────────────────────────────────────────────────────

def _atr(df_slice: pd.DataFrame, period: int = 14) -> float:
    """ATR over last `period` bars of slice. Falls back to mean(HL) if too short."""
    n = len(df_slice)
    if n < 2:
        hl = float((df_slice["high"] - df_slice["low"]).mean())
        return max(hl, 1e-9)
    hi = df_slice["high"].to_numpy(dtype=np.float64)
    lo = df_slice["low"].to_numpy(dtype=np.float64)
    cl = df_slice["close"].to_numpy(dtype=np.float64)
    prev = cl[:-1]
    tr   = np.maximum(hi[1:] - lo[1:],
           np.maximum(np.abs(hi[1:] - prev), np.abs(lo[1:] - prev)))
    w = min(period, len(tr))
    return max(float(np.mean(tr[-w:])), 1e-9)


# ── Swing detector (3-bar pivot) ──────────────────────────────────────────────

def _find_swings(hi: np.ndarray, lo: np.ndarray) -> List[float]:
    """Return list of pivot prices (highs and lows) in the slice."""
    pivots: List[float] = []
    for i in range(1, len(hi) - 1):
        if hi[i] > hi[i-1] and hi[i] > hi[i+1]:
            pivots.append(hi[i])
        if lo[i] < lo[i-1] and lo[i] < lo[i+1]:
            pivots.append(lo[i])
    return pivots


# ── Main extraction ───────────────────────────────────────────────────────────

def extract_detection_features(
    df: pd.DataFrame,
    start: int,
    end: int,
    box_high: float,
    box_low: float,
) -> Optional[Dict[str, float]]:
    """
    Parameters
    ----------
    df        : full candle DataFrame (only df.iloc[:end+1] used internally)
    start     : integer index of box start candle
    end       : integer index of box end candle (inclusive)
    box_high  : detected top price of the box
    box_low   : detected bottom price of the box

    Returns
    -------
    dict of 10 float features, or None if extraction fails.
    """
    try:
        n = len(df)
        # Safety clamp
        start = max(0, int(start))
        end   = min(n - 1, int(end))
        if end <= start:
            return None

        box_slice  = df.iloc[start : end + 1]
        pre_start  = max(0, start - 30)
        pre_slice  = df.iloc[pre_start : start]   # 30 bars before box

        duration = end - start + 1

        # ATRs
        box_atr = _atr(box_slice)
        pre_atr = _atr(pre_slice) if len(pre_slice) >= 2 else box_atr

        box_range = float(box_high - box_low)

        # ── 1. range_norm ─────────────────────────────────────────────────────
        range_norm = box_range / pre_atr

        # ── 2. volatility_compression ─────────────────────────────────────────
        volatility_compression = box_atr / pre_atr

        # ── 3. avg_candle_size ────────────────────────────────────────────────
        candle_ranges = (box_slice["high"] - box_slice["low"]).to_numpy(dtype=np.float64)
        avg_candle_size = float(np.mean(candle_ranges)) / pre_atr

        # ── 4. wick_ratio ─────────────────────────────────────────────────────
        opens   = box_slice["open"].to_numpy(dtype=np.float64)
        closes  = box_slice["close"].to_numpy(dtype=np.float64)
        highs   = box_slice["high"].to_numpy(dtype=np.float64)
        lows    = box_slice["low"].to_numpy(dtype=np.float64)
        bodies  = np.abs(closes - opens)
        upper_w = highs  - np.maximum(opens, closes)
        lower_w = np.minimum(opens, closes) - lows
        total_w = upper_w + lower_w
        total_w = np.where(total_w < 1e-9, 1e-9, total_w)
        ranges_ = np.where(candle_ranges < 1e-9, 1e-9, candle_ranges)
        wick_ratio = float(np.mean(total_w / ranges_))

        # ── 5. top_touches ────────────────────────────────────────────────────
        thresh = 0.10 * box_range if box_range > 1e-9 else 1e-9
        top_touches = int(np.sum(closes >= (box_high - thresh)))
        bot_touches = int(np.sum(closes <= (box_low  + thresh)))

        # ── 6. pre_trend_slope ────────────────────────────────────────────────
        pre_trend_slope = 0.0
        if len(pre_slice) >= 4:
            cl_arr  = pre_slice["close"].to_numpy(dtype=np.float64)
            x       = np.arange(len(cl_arr), dtype=np.float64)
            slope, _ = np.polyfit(x, cl_arr, 1)
            pre_trend_slope = float(slope) / pre_atr

        # ── 7. impulse_dist ───────────────────────────────────────────────────
        impulse_dist = 0.0
        if len(pre_slice) >= 3:
            ph = pre_slice["high"].to_numpy(dtype=np.float64)
            pl = pre_slice["low"].to_numpy(dtype=np.float64)
            pivots = _find_swings(ph, pl)
            if pivots:
                box_mid = (box_high + box_low) / 2.0
                dists   = [abs(p - box_mid) for p in pivots]
                impulse_dist = float(min(dists)) / pre_atr

        # ── 8. time_in_range_pct ─────────────────────────────────────────────
        in_range = np.sum((closes >= box_low) & (closes <= box_high))
        time_in_range_pct = float(in_range) / max(duration, 1)

        feats: Dict[str, float] = {
            "duration_bars":          float(duration),
            "range_norm":             float(range_norm),
            "volatility_compression": float(volatility_compression),
            "avg_candle_size":        float(avg_candle_size),
            "wick_ratio":             float(wick_ratio),
            "top_touches":            float(top_touches),
            "bot_touches":            float(bot_touches),
            "pre_trend_slope":        float(pre_trend_slope),
            "impulse_dist":           float(impulse_dist),
            "time_in_range_pct":      float(time_in_range_pct),
        }

        # ── Sanity checks ─────────────────────────────────────────────────────
        for k, v in feats.items():
            if not np.isfinite(v):
                logger.warning("detection_features: non-finite %s=%s — clamping to 0", k, v)
                feats[k] = 0.0

        # Leakage guard
        for bad_key in _LEAKAGE_KEYS:
            if bad_key in feats:
                raise ValueError(f"Leakage: {bad_key} found in feature dict")

        assert len(feats) == EXPECTED_FEATURE_COUNT, (
            f"Feature count mismatch: {len(feats)} != {EXPECTED_FEATURE_COUNT}"
        )

        # Debug logging (min/max per feature at DEBUG level)
        if logger.isEnabledFor(logging.DEBUG):
            for k, v in feats.items():
                logger.debug("  feature %-28s = %.6f", k, v)

        return feats

    except Exception as exc:
        logger.warning("extract_detection_features failed (start=%s end=%s): %s", start, end, exc)
        return None
