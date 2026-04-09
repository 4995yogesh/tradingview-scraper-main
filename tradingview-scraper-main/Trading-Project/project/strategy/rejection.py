from typing import List, Dict

def detect_trap(candles: List[Dict], consolidation_zone: dict) -> dict:
    """
    Detects false breakouts (trap / rejection).
    1. Wick rejection: wick >= 60% of candle, breaks range, closes inside.
    2. Two-candle reversal: Strong candle breaks, next strong candle reverses and closes inside.
    """
    if not consolidation_zone.get("valid") or len(candles) < 2:
        return {"is_trap": False, "direction": None}

    latest = candles[-1]
    prev = candles[-2]
    
    zone_high = consolidation_zone["high"]
    zone_low = consolidation_zone["low"]

    # --- 1. Wick Rejection ---
    high, low, open_p, close = latest["high"], latest["low"], latest["open"], latest["close"]
    total_size = high - low
    
    if total_size > 0:
        upper_wick = high - max(open_p, close)
        lower_wick = min(open_p, close) - low
        
        # Bullish Trap (buying trapped -> bearish result)
        if high > zone_high and max(open_p, close) <= zone_high:
            if (upper_wick / total_size) >= 0.6:
                return {"is_trap": True, "direction": "bearish"}
                
        # Bearish Trap (selling trapped -> bullish result)
        if low < zone_low and min(open_p, close) >= zone_low:
            if (lower_wick / total_size) >= 0.6:
                return {"is_trap": True, "direction": "bullish"}

    # --- 2. Two-Candle Reversal ---
    prev_body = abs(prev["close"] - prev["open"])
    latest_body = abs(close - open_p)
    
    # Bullish break followed by bearish drop
    if prev["close"] > zone_high and prev["close"] > prev["open"]:
        if close < open_p and close < zone_high:
            prev_midpoint = (prev["high"] + prev["low"]) / 2
            if close <= prev_midpoint:
                return {"is_trap": True, "direction": "bearish"}

    # Bearish break followed by bullish pump
    if prev["close"] < zone_low and prev["close"] < prev["open"]:
        if close > open_p and close > zone_low:
            prev_midpoint = (prev["high"] + prev["low"]) / 2
            if close >= prev_midpoint:
                return {"is_trap": True, "direction": "bullish"}
                
    return {"is_trap": False, "direction": None}
