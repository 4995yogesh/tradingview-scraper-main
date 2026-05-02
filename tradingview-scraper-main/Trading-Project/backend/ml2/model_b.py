import numpy as np

def extract_box(heatmap: np.ndarray, candles: list, threshold=0.5) -> dict | None:
    thresholded = heatmap > threshold
    if not np.any(thresholded):
        return None
    
    starts, ends = [], []
    start_idx = None
    for i, val in enumerate(thresholded):
        if val and start_idx is None:
            start_idx = i
        elif not val and start_idx is not None:
            starts.append(start_idx)
            ends.append(i - 1)
            start_idx = None
    if start_idx is not None:
        starts.append(start_idx)
        ends.append(len(thresholded) - 1)
    
    if not starts:
        return None
    
    longest_idx = np.argmax(np.array(ends) - np.array(starts) + 1)
    start_idx, end_idx = starts[longest_idx], ends[longest_idx]
    
    priceHigh = max(c['high'] for c in candles[start_idx:end_idx + 1])
    priceLow = min(c['low'] for c in candles[start_idx:end_idx + 1])
    confidence = np.mean(heatmap[start_idx:end_idx + 1])
    
    return {
        'timeStart': candles[start_idx]['time'],
        'timeEnd': candles[end_idx]['time'],
        'priceHigh': priceHigh,
        'priceLow': priceLow,
        'start_idx': start_idx,
        'end_idx': end_idx,
        'confidence': confidence
    }

def refine_box_boundaries(box, candles, heatmap) -> dict:
    start_idx, end_idx = box['start_idx'], box['end_idx']
    
    while start_idx < end_idx and heatmap[start_idx] < 0.3:
        start_idx += 1
    while end_idx > start_idx and heatmap[end_idx] < 0.3:
        end_idx -= 1
    
    if start_idx > end_idx:
        return None
    
    priceHigh = max(c['high'] for c in candles[start_idx:end_idx + 1])
    priceLow = min(c['low'] for c in candles[start_idx:end_idx + 1])
    confidence = np.mean(heatmap[start_idx:end_idx + 1])
    
    return {
        'timeStart': candles[start_idx]['time'],
        'timeEnd': candles[end_idx]['time'],
        'priceHigh': priceHigh,
        'priceLow': priceLow,
        'start_idx': start_idx,
        'end_idx': end_idx,
        'confidence': confidence
    }