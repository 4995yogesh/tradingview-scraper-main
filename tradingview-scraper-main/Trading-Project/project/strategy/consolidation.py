"""
Consolidation detector (price action based)
"""

from typing import List, Dict

def detect_all_consolidations(candles: List[Dict], length: int = 5, range_threshold: float = 0.02) -> List[dict]:
    """Detect consolidation zones.
    A zone is active when (high - low) / close < range_threshold over `length` candles.
    Returns list of boxes with start/end indices, top/bottom prices and timestamps.
    """
    boxes: List[dict] = []
    current: dict | None = None
    for i in range(len(candles)):
        if i < length:
            continue
        window = candles[i - length + 1 : i + 1]
        high = max(c["high"] for c in window)
        low = min(c["low"] for c in window)
        close = candles[i]["close"]
        if close == 0:
            continue
        if (high - low) / close < range_threshold:
            start_idx = i - length + 1
            if current is None:
                current = {
                    "start_index": start_idx,
                    "end_index": i,
                    "top": high,
                    "bottom": low,
                    "timeStart": candles[start_idx]["timestamp"],
                    "timeEnd": candles[i]["timestamp"],
                }
            else:
                current["end_index"] = i
                current["top"] = max(current["top"], high)
                current["bottom"] = min(current["bottom"], low)
                current["timeEnd"] = candles[i]["timestamp"]
        else:
            if current is not None:
                boxes.append(current)
                current = None
    if current is not None:
        boxes.append(current)
    return boxes
