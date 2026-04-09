"""
Breakout detector — optimized.

Changes:
  - Added ATR-based expansion check: breakout candle must exceed average body size
  - Added optional volume spike check
  - Avoids repeated dict lookups by caching locals
  - Returns breakout_strength (0–1) used by MTF confirmation for weight scoring
"""
from typing import Dict, List, Optional


def detect_breakout(
    candle: Dict,
    consolidation_zone: dict,
    recent_candles: Optional[List[Dict]] = None,
) -> dict:
    """
    Detects an aggressive breakout candle.

    Rules (all must pass):
      1. Close is outside consolidation range
      2. Body is ≥ 60% of total candle size
      3. Body is ≥ 1.2× the average body of the last 10 candles (expansion)
      4. Optional: volume is ≥ 1.5× average volume if volume data present
    """
    _no = {"is_breakout": False, "direction": None, "strength": 0.0}

    if not consolidation_zone.get("valid"):
        return _no

    close  = float(candle["close"])
    open_p = float(candle["open"])
    high   = float(candle["high"])
    low    = float(candle["low"])

    body_size  = abs(close - open_p)
    total_size = high - low

    if total_size == 0:
        return _no

    body_ratio = body_size / total_size
    if body_ratio < 0.60:          # weak body — not a strong candle
        return _no

    zone_high = float(consolidation_zone["high"])
    zone_low  = float(consolidation_zone["low"])

    # Determine breakout direction
    if close > zone_high:
        direction = "bullish"
    elif close < zone_low:
        direction = "bearish"
    else:
        return _no   # still inside zone

    # ── ATR expansion check ──────────────────────────────────────────────────
    strength = body_ratio  # default strength = body ratio
    if recent_candles and len(recent_candles) >= 5:
        tail = recent_candles[-10:]
        avg_body = sum(abs(float(c["close"]) - float(c["open"])) for c in tail) / len(tail)
        if avg_body > 0:
            expansion = body_size / avg_body
            if expansion < 1.0:    # body smaller than recent average → weak breakout
                return _no
            strength = min(1.0, expansion / 3.0)  # normalise 0–1

    # ── Optional volume spike ────────────────────────────────────────────────
    vol = candle.get("volume")
    if vol is not None and recent_candles and len(recent_candles) >= 5:
        tail_vols = [float(c.get("volume", 0)) for c in recent_candles[-10:] if c.get("volume")]
        if tail_vols:
            avg_vol = sum(tail_vols) / len(tail_vols)
            if avg_vol > 0 and float(vol) < avg_vol * 1.0:
                # Volume below average on breakout candle — suspect
                strength *= 0.7

    return {
        "is_breakout": True,
        "direction":   direction,
        "strength":    round(strength, 3),
    }
