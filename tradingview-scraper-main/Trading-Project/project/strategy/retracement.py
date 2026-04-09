from typing import List, Dict

def detect_retracement(candles: List[Dict], direction: str) -> dict:
    """
    Detects simple retracement (pullback).
    If bullish direction: look for a short-term lower high / lower low against major trend.
    """
    if len(candles) < 3:
        return {"valid": False}
        
    latest = candles[-1]
    prev = candles[-2]
    
    if direction == "bullish":
        if latest["close"] < prev["close"] and latest["close"] > candles[0]["open"]:
            return {"valid": True, "type": "bullish_retracement"}
    elif direction == "bearish":
        if latest["close"] > prev["close"] and latest["close"] < candles[0]["open"]:
            return {"valid": True, "type": "bearish_retracement"}
            
    return {"valid": False}
