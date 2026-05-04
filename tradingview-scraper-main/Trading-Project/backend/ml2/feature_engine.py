import numpy as np
import torch
from scipy.stats import linregress

def build_features(ohlc_array: np.ndarray, window_n: int = 10) -> torch.Tensor:
    """
    Upgraded feature engine: 12 legacy channels + 6 structural range channels.
    Input: ohlc_array shape [N, 4] -> (Open, High, Low, Close)
    Output: torch.Tensor shape [N, 18]
    """
    eps = 1e-8
    n = len(ohlc_array)
    
    # ── RAW CHANNELS ──────────────────────────────────────────────────────────
    opens  = ohlc_array[:, 0]
    highs  = ohlc_array[:, 1]
    lows   = ohlc_array[:, 2]
    closes = ohlc_array[:, 3]
    
    # ── LEGACY CHANNELS (1-12) ────────────────────────────────────────────────
    # Ch 1-4: OHLC (Standard normalization via ATR happens later or externally, 
    # but here we follow the provided logic from the existing pipeline)
    
    # Ch 5: Body Size
    body_size = np.abs(closes - opens)
    # Ch 6: Candle Range
    candle_range = highs - lows
    # Ch 7-8: Wicks
    upper_wick = highs - np.maximum(opens, closes)
    lower_wick = np.minimum(opens, closes) - lows
    # Ch 9: Direction
    direction = np.sign(closes - opens)
    
    # Ch 10: Volatility Ratio (Range / SMA(Range, 14))
    rmr_len = len(candle_range)
    if rmr_len > 0:
        rolling_mean_range = np.convolve(candle_range, np.ones(14)/14, mode='full')[:rmr_len]
        safe_idx = min(13, rmr_len - 1)
        if safe_idx >= 0:
            rolling_mean_range[:safe_idx+1] = rolling_mean_range[safe_idx]
    else:
        rolling_mean_range = np.zeros_like(candle_range)
    volatility_ratio = candle_range / (rolling_mean_range + eps)
    volatility_ratio = np.clip(volatility_ratio, 0, 100)
    
    # Ch 11: Momentum (close_t - close_{t-3})
    momentum = np.zeros_like(closes)
    if len(closes) > 3:
        momentum[3:] = closes[3:] - closes[:-3]
    
    # Ch 12: Local Trend (10-period linreg slope)
    local_trend = np.zeros_like(closes)
    for i in range(10, len(closes)):
        # Vectorized internal but loop for the sliding window per requirement 
        # (Though technically can be optimized further, this maintains existing logic)
        slope, _, _, _, _ = linregress(np.arange(10), closes[i-10:i])
        local_trend[i] = slope

    # ── NEW CHANNELS (13-18) ──────────────────────────────────────────────────
    
    # Efficient Rolling Windows using sliding_window_view (NumPy 1.20+)
    # For older numpy compatibility, we use a manual stride trick or padding
    def get_rolling_view(arr, window):
        shape = (arr.size - window + 1, window)
        strides = (arr.strides[0], arr.strides[0])
        return np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)

    # Pad inputs to maintain original length
    pad_highs = np.concatenate([np.full(window_n-1, highs[0]), highs])
    pad_lows  = np.concatenate([np.full(window_n-1, lows[0]), lows])
    
    view_h = get_rolling_view(pad_highs, window_n)
    view_l = get_rolling_view(pad_lows, window_n)
    
    # Ch 13: Rolling High
    rolling_high = np.max(view_h, axis=1)
    # Ch 14: Rolling Low
    rolling_low = np.min(view_l, axis=1)
    # Ch 15: Range Width
    range_width = rolling_high - rolling_low
    
    # Ch 16: Range Stability (std of range_width over window N)
    pad_width = np.concatenate([np.full(window_n-1, range_width[0]), range_width])
    view_w = get_rolling_view(pad_width, window_n)
    range_stability = np.std(view_w, axis=1)
    
    # Ch 17: Candle Overlap Ratio (Intersection over Union)
    # intersection = max(0, min(high_t, high_t-1) - max(low_t, low_t-1))
    h_t = highs
    h_prev = np.concatenate([[highs[0]], highs[:-1]])
    l_t = lows
    l_prev = np.concatenate([[lows[0]], lows[:-1]])
    
    inter = np.maximum(0, np.minimum(h_t, h_prev) - np.maximum(l_t, l_prev))
    union = np.maximum(h_t, h_prev) - np.minimum(l_t, l_prev)
    overlap_ratio = inter / (union + eps)
    
    # Ch 18: Boundary Proximity (Normalized)
    # boundary_proximity = min(abs(high - rolling_high), abs(low - rolling_low)) / (range_width + eps)
    dist_top = np.abs(highs - rolling_high)
    dist_bot = np.abs(lows - rolling_low)
    boundary_proximity = np.minimum(dist_top, dist_bot) / (range_width + eps)
    
    # ── ASSEMBLY ──────────────────────────────────────────────────────────────
    # Combine all 18 channels
    # Note: Ch 1-4 are raw OHLC here. In production, these should be ATR-normalized.
    # We follow the 12-channel order strictly.
    features = np.column_stack((
        opens, highs, lows, closes,        # 1-4
        body_size, candle_range,           # 5-6
        upper_wick, lower_wick,            # 7-8
        direction, volatility_ratio,       # 9-10
        momentum, local_trend,             # 11-12
        rolling_high, rolling_low,         # 13-14
        range_width, range_stability,      # 15-16
        overlap_ratio, boundary_proximity  # 17-18
    ))
    
    return torch.from_numpy(features.astype(np.float32))

# ── VALIDATION ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Synthetic OHLC data (50 candles)
    np.random.seed(42)
    base_price = 100.0
    synth_ohlc = []
    for i in range(50):
        o = base_price + np.random.normal(0, 0.5)
        c = o + np.random.normal(0, 0.3)
        h = max(o, c) + abs(np.random.normal(0, 0.2))
        l = min(o, c) - abs(np.random.normal(0, 0.2))
        synth_ohlc.append([o, h, l, c])
        base_price = c
        
    data = np.array(synth_ohlc)
    tensor = build_features(data)
    
    print(f"Output Shape: {tensor.shape}")
    print(f"Sample (Last Candle):\n{tensor[-1]}")
    
    # Check for NaNs/Infs
    has_nan = torch.isnan(tensor).any()
    has_inf = torch.isinf(tensor).any()
    print(f"Contains NaN: {has_nan}")
    print(f"Contains Inf: {has_inf}")
    
    # Channel verification
    assert tensor.shape[1] == 18, "Channel count mismatch"
    print("Verification Successful: 18-channel pipeline active.")
