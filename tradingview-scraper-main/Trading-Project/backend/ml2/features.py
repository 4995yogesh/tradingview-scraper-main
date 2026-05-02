import numpy as np
from scipy.stats import linregress

def compute_features(candles: list[dict]) -> np.ndarray:
    opens = np.array([c['open'] for c in candles])
    highs = np.array([c['high'] for c in candles])
    lows = np.array([c['low'] for c in candles])
    closes = np.array([c['close'] for c in candles])
    
    body_size = np.abs(closes - opens)
    candle_range = highs - lows
    upper_wick = highs - np.maximum(opens, closes)
    lower_wick = np.minimum(opens, closes) - lows
    direction = np.sign(closes - opens)
    
    rmr_len = len(candle_range)
    if rmr_len > 0:
        rolling_mean_range = np.convolve(candle_range, np.ones(14)/14, mode='full')[:rmr_len]
        safe_idx = min(13, rmr_len - 1)
        if safe_idx >= 0:
            rolling_mean_range[:safe_idx+1] = rolling_mean_range[safe_idx]
    else:
        rolling_mean_range = np.array([])
    
    volatility_ratio = candle_range / (rolling_mean_range + 1e-9)
    volatility_ratio = np.clip(volatility_ratio, 0, 100)
    
    momentum = np.zeros_like(closes)
    if len(closes) > 3:
        momentum[3:] = closes[3:] - closes[:-3]
    
    local_trend = np.zeros_like(closes)
    for i in range(10, len(closes)):
        try:
            slope, _, _, _, _ = linregress(np.arange(10), closes[i-10:i])
            local_trend[i] = slope
        except Exception:
            local_trend[i] = 0
    
    features = np.column_stack((opens, highs, lows, closes, body_size, candle_range, upper_wick, lower_wick, direction, volatility_ratio, momentum, local_trend))
    return features

def normalize_features(features: np.ndarray, atr_window=14) -> np.ndarray:
    highs = features[:, 1]
    lows = features[:, 2]
    closes = features[:, 3]
    
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))))
    atr = np.convolve(tr, np.ones(atr_window)/atr_window, mode='full')[:len(tr)]
    atr_len = len(atr)
    if atr_len > 0:
        safe_idx = min(atr_window - 1, atr_len - 1)
        if safe_idx >= 0:
            atr[:safe_idx+1] = atr[safe_idx]
    
    normalized_features = features.copy()
    normalized_features[:, :4] /= atr[:, np.newaxis]
    return normalized_features