"""
Consolidation detector — optimized.

Changes:
  - Single-pass extraction of highs/lows (was 2 separate list comprehensions)
  - Early-exit before touch counting if range is already too wide
  - Denominator cached to avoid redundant division
  - Returns zone midpoint + ATR-equivalent zone_height for downstream use
"""
from typing import List, Dict


def detect_consolidation(
    candles: List[Dict],
    lookback_min: int = 5,
    lookback_max: int = 15,
    tolerance_pct: float = 0.001,
) -> dict:
    """
    Detects a consolidation zone in the most-recent N candles (5–15).
    A zone is valid when:
      - Price is bound within tolerance_pct * 10 (1%) range
      - At least 2 wick touches on both high and low boundaries
    """
    if len(candles) < lookback_min:
        return {"valid": False, "high": None, "low": None, "mid": None, "height": None}

    n = min(len(candles), lookback_max)
    recent = candles[-n:]

    # Single-pass: extract highs and lows together
    highs = [0.0] * n
    lows  = [0.0] * n
    for i, c in enumerate(recent):
        highs[i] = float(c["high"])
        lows[i]  = float(c["low"])

    range_high = max(highs)
    range_low  = min(lows)

    # ── Early exit: range too wide ───────────────────────────────────────────
    # Cache denominator for all subsequent pct calculations
    if range_low == 0.0:
        return {"valid": False, "high": None, "low": None, "mid": None, "height": None}

    zone_height    = range_high - range_low
    range_size_pct = zone_height / range_low

    if range_size_pct > tolerance_pct * 10:   # > 1% → not tight enough
        return {"valid": False, "high": None, "low": None, "mid": None, "height": None}

    # ── Touch counting ───────────────────────────────────────────────────────
    touch_threshold = tolerance_pct  # within 0.1% of boundary
    touches_high = sum(1 for h in highs if abs(h - range_high) / range_high < touch_threshold)
    touches_low  = sum(1 for l in lows  if abs(l - range_low)  / range_low  < touch_threshold)

    if touches_high >= 2 and touches_low >= 2:
        return {
            "valid":  True,
            "high":   range_high,
            "low":    range_low,
            "mid":    (range_high + range_low) / 2.0,
            "height": zone_height,
        }

    return {"valid": False, "high": None, "low": None, "mid": None, "height": None}
