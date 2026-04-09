from typing import List, Dict

def compute_liquidity_entry(recent_candles: List[Dict], trap_direction: str) -> dict:
    """
    Liquidity Model:
    After a trap (rejection confirmed):
    Wait max 6 candles to detect a swing high/low break.
    - entry = break of swing
    - SL = extreme formed before break
    """
    # Requires at least 3 candles to find a swing
    if len(recent_candles) < 3:
        return {"valid": False}
        
    # Limit to max 6 candles after trap
    candles = recent_candles[-6:]
    
    if trap_direction == "bullish":
        # We look for a swing high to be broken for entry
        # A swing high is a high flanked by two lower highs
        for i in range(1, len(candles)-1):
            if candles[i]["high"] > candles[i-1]["high"] and candles[i]["high"] > candles[i+1]["high"]:
                swing_high = candles[i]["high"]
                # SL is lowest low formed before this break
                sl = min([c["low"] for c in candles[:i+2]]) 
                return {
                    "valid": True,
                    "entry": swing_high,
                    "sl": sl
                }
    elif trap_direction == "bearish":
        # Look for swing low to be broken for short entry
        for i in range(1, len(candles)-1):
            if candles[i]["low"] < candles[i-1]["low"] and candles[i]["low"] < candles[i+1]["low"]:
                swing_low = candles[i]["low"]
                # SL is highest high formed before this break
                sl = max([c["high"] for c in candles[:i+2]])
                return {
                    "valid": True,
                    "entry": swing_low,
                    "sl": sl
                }
                
    return {"valid": False}
