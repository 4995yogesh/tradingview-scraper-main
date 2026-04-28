import numpy as np
import math

def _safe_div(n, d):
    return n / d if d != 0 else 0.0

def extract_quality_features(candles, box_high, box_low):
    """
    Compute behavior-focused regression features (v2).
    """
    if not candles:
        return [0.0] * 19
    
    cl = np.array([float(c['close']) for c in candles])
    hi = np.array([float(c['high']) for c in candles])
    lo = np.array([float(c['low']) for c in candles])
    op = np.array([float(c['open']) for c in candles])
    
    mid_price = (box_high + box_low) / 2.0 + 1e-9
    box_height = box_high - box_low
    duration = float(len(candles))
    
    # 1. Scale-Invariant Geometry
    log_duration = np.log(duration + 1)
    duration_penalty = 1.0 / (duration + 1)
    range_width_norm = box_height / mid_price
    variation_norm = np.std((hi - lo) / mid_price)
    mid_deviation = _safe_div(abs(cl[-1] - mid_price), box_height)
    
    # 2. Volatility & Flatness
    returns = np.abs(np.diff(cl) / (cl[:-1] + 1e-9))
    volatility_spike_raw = _safe_div(np.max(returns) if len(returns)>0 else 0, np.mean(returns) if len(returns)>0 else 1)
    volatility_spike = np.log(1 + volatility_spike_raw)
    flatness = np.std(cl / mid_price) * 100.0
    
    bodies = np.abs(cl - op)
    ranges = hi - lo
    body_shrink = _safe_div(np.mean(bodies), np.mean(ranges))
    slope = _safe_div(cl[-1] - cl[0], duration * mid_price)
    
    # 3. Behavioral Boundaries
    threshold = 0.05 * box_height
    touches_hi = np.sum(box_high - hi < threshold)
    touches_lo = np.sum(lo - box_low < threshold)
    touch_count = float(touches_hi + touches_lo)
    symmetry = _safe_div(float(touches_hi), float(touches_lo + 0.1))
    
    # Rejection Rate (amplified)
    rejections = (hi >= box_high - threshold) & (cl < op)
    rejection_rate = np.mean(rejections) * 2.0
    
    boundary_time_ratio = (np.mean(hi >= box_high - threshold) + np.mean(lo <= box_low + threshold)) * 1.5
    
    # Respect score
    inside = np.sum((hi <= box_high + threshold) & (lo >= box_low - threshold))
    respect_score = _safe_div(float(inside), duration)
    
    # Interaction (compressed)
    raw_interaction = touch_count * respect_score
    quality_interaction = np.log(1 + raw_interaction) * 0.5
    
    # Wick Ratio
    upper_wicks = box_high - np.maximum(op, cl)
    lower_wicks = np.minimum(op, cl) - box_low
    wick_ratio = _safe_div(np.sum(upper_wicks) + np.sum(lower_wicks), np.sum(ranges))

    # 4. Internal Efficiency & Movement
    path_length = np.sum(np.abs(np.diff(cl)))
    movement_efficiency_base = box_height / (path_length + 1e-6)
    movement_efficiency = movement_efficiency_base * 1.5

    price_diff = np.diff(cl)
    direction_changes = 0
    if len(price_diff) > 1:
        direction_changes = np.sum(np.sign(price_diff[:-1]) != np.sign(price_diff[1:]))
    direction_consistency = 1.0 / (direction_changes + 1.0)

    # 5. Composite Behavioral Features
    behavior_score = rejection_rate * boundary_time_ratio * movement_efficiency
    structure_penalty = (1.0 - movement_efficiency_base) * (1.0 - (rejection_rate / 2.0)) # use raw rej rate

    overlaps = []
    for i in range(1, len(candles)):
        ov = min(hi[i], hi[i-1]) - max(lo[i], lo[i-1])
        overlaps.append(max(0, ov))
    avg_overlap = np.mean(overlaps) / mid_price if overlaps else 0.0
    
    directional_bias = _safe_div(cl[-1] - cl[0], box_height)
    
    hist, _ = np.histogram(cl, bins=5)
    probs = hist / len(cl)
    entropy_raw = -np.sum(probs * np.log2(probs + 1e-9))
    entropy = np.log(1 + abs(entropy_raw)) * 0.5

    return [
        log_duration, duration_penalty, range_width_norm, variation_norm,
        mid_deviation, body_shrink, slope, touch_count, symmetry,
        respect_score, wick_ratio, avg_overlap, directional_bias, entropy,
        flatness, boundary_time_ratio, volatility_spike, rejection_rate,
        quality_interaction, movement_efficiency, behavior_score,
        structure_penalty, direction_consistency
    ]

FEATURE_NAMES = [
    "log_duration", "duration_penalty", "range_width_norm", "variation_norm",
    "mid_deviation", "body_shrink", "slope", "touch_count", "symmetry",
    "respect_score", "wick_ratio", "avg_overlap", "directional_bias", "entropy",
    "flatness", "boundary_time_ratio", "volatility_spike", "rejection_rate",
    "quality_interaction", "movement_efficiency", "behavior_score",
    "structure_penalty", "direction_consistency"
]

class QualityExtractor:
    def __init__(self, candle_fetcher_fn):
        self.fetcher = candle_fetcher_fn

    def extract(self, box):
        try:
            exchange = box.get("exchange", "OANDA")
            symbol = box.get("symbol", "EURUSD")
            tf = box.get("timeframe", "1d")
            
            # Fetch enough candles to cover the box
            candles = self.fetcher(exchange, symbol, tf, count=1000)
            if not candles:
                return None
                
            # Filter candles to box range
            start_ms = box.get("timeStart") or box.get("start")
            end_ms = box.get("timeEnd") or box.get("end")
            
            if not start_ms or not end_ms:
                return None
                
            # Support both ms and sec
            if start_ms < 1e11: start_ms *= 1000
            if end_ms < 1e11: end_ms *= 1000
            
            box_candles = []
            for c in candles:
                ts = c.get("ts") or c.get("time")
                if isinstance(ts, str): # daily/weekly
                    import pandas as pd
                    ts = int(pd.Timestamp(ts).timestamp() * 1000)
                elif ts < 1e11: # sec to ms
                    ts *= 1000
                
                if start_ms <= ts <= end_ms:
                    box_candles.append(c)
            
            if not box_candles:
                return None
                
            return extract_quality_features(box_candles, box['priceHigh'], box['priceLow'])
        except Exception:
            return None
