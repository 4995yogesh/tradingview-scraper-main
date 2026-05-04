import torch
import numpy as np

def build_features(ohlc: np.ndarray) -> torch.Tensor:
    """
    Upgraded Feature Engine v2.1
    Input: ohlc array [N, 4] -> (Open, High, Low, Close)
    Output: torch.Tensor [N, 21]
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    t_ohlc = torch.from_numpy(ohlc).float().to(device)
    
    n = t_ohlc.shape[0]
    eps = 1e-8
    
    # Extract components
    opens  = t_ohlc[:, 0]
    highs  = t_ohlc[:, 1]
    lows   = t_ohlc[:, 2]
    closes = t_ohlc[:, 3]
    
    # ── Step 0: ATR Calculation (Window=14) ──────────────────────────────────
    # TR = max(H-L, |H-Cp|, |L-Cp|)
    c_prev = torch.cat([closes[0:1], closes[:-1]])
    tr = torch.max(
        highs - lows,
        torch.max(torch.abs(highs - c_prev), torch.abs(lows - c_prev))
    )
    # ATR using convolution (simple SMA)
    atr_kernel = torch.ones(1, 1, 14, device=device) / 14
    atr = torch.nn.functional.conv1d(
        tr.view(1, 1, -1), atr_kernel, padding=13
    ).view(-1)[:n]
    # Handle padding edges — robust to n < 14
    if n > 13:
        atr[:13] = atr[13]
    else:
        # Fallback for very small windows
        atr[:] = torch.mean(tr) if n > 0 else eps
    atr = torch.clamp(atr, min=eps)

    # ── Channels 1-4: OHLC Normalized ─────────────────────────────────────────
    ohlc_norm = t_ohlc / atr.view(-1, 1)
    
    # ── Channels 5-9: Geometry ───────────────────────────────────────────────
    body_size = torch.abs(closes - opens) / atr
    c_range   = (highs - lows) / atr
    u_wick    = (highs - torch.max(opens, closes)) / atr
    l_wick    = (torch.min(opens, closes) - lows) / atr
    direction = torch.sign(closes - opens)
    
    # ── Channels 10-12: Dynamics ─────────────────────────────────────────────
    # 10: Volatility Ratio (Range / SMA(Range, 14))
    r_kernel = torch.ones(1, 1, 14, device=device) / 14
    sma_range = torch.nn.functional.conv1d(
        (highs - lows).view(1, 1, -1), r_kernel, padding=13
    ).view(-1)[:n]
    if n > 13:
        sma_range[:13] = sma_range[13]
    else:
        sma_range[:] = torch.mean(highs - lows)
    vol_ratio = (highs - lows) / (sma_range + eps)
    
    # 11: Momentum (close_t - close_t-3) / ATR
    mom_3 = torch.zeros_like(closes)
    mom_3[3:] = (closes[3:] - closes[:-3]) / atr[3:]
    
    # 12: Slope (Simple 10-period price delta as slope proxy for speed)
    # Using a simple delta for vectorization, normalized by ATR
    slope = torch.zeros_like(closes)
    slope[10:] = (closes[10:] - closes[:-10]) / (10 * atr[10:])

    # ── Channels 13-14: Rolling High/Low (Window=10) ──────────────────────────
    if n >= 10:
        h_unfold = highs.unfold(0, 10, 1)
        l_unfold = lows.unfold(0, 10, 1)
        r_high_vals = torch.max(h_unfold, dim=1).values
        r_low_vals  = torch.min(l_unfold, dim=1).values
        # Padding to match length
        r_high = torch.cat([torch.full((9,), r_high_vals[0], device=device), r_high_vals])
        r_low  = torch.cat([torch.full((9,), r_low_vals[0], device=device), r_low_vals])
    else:
        # Fallback for n < 10
        r_high = torch.full((n,), torch.max(highs), device=device)
        r_low  = torch.full((n,), torch.min(lows), device=device)
    
    # Normalize by ATR (as they are price levels)
    r_high_norm = r_high / atr
    r_low_norm  = r_low / atr

    # ── Channels 15-16: Range Meta ────────────────────────────────────────────
    r_width = (r_high - r_low) # Raw for stability calc
    r_width_norm = r_width / atr # 15: Range Width
    
    # 16: Range Stability (Std(r_width, 10) / Mean(r_width, 10))
    if n >= 10:
        w_unfold = r_width.unfold(0, 10, 1)
        w_std  = torch.std(w_unfold, dim=1)
        w_mean = torch.mean(w_unfold, dim=1)
        r_stability_vals = w_std / (w_mean + eps)
        r_stability = torch.cat([torch.full((9,), r_stability_vals[0], device=device), r_stability_vals])
    else:
        r_stability = torch.zeros(n, device=device)

    # ── Channel 17: Overlap Ratio (IOU) ───────────────────────────────────────
    h_prev = torch.cat([highs[0:1], highs[:-1]])
    l_prev = torch.cat([lows[0:1], lows[:-1]])
    
    inter = torch.clamp(torch.min(highs, h_prev) - torch.max(lows, l_prev), min=0)
    union = torch.max(highs, h_prev) - torch.min(lows, l_prev)
    overlap = torch.clamp(inter / (union + eps), 0, 1)

    # ── Channel 18: Signed Boundary Proximity ─────────────────────────────────
    dist_top = torch.abs(highs - r_high) / (r_width + eps)
    dist_bot = torch.abs(lows - r_low) / (r_width + eps)
    # Signed variant: positive if closer to top, negative if closer to bottom
    # min_dist * sign
    min_dist = torch.min(dist_top, dist_bot)
    side_flag = torch.where(dist_top < dist_bot, torch.tensor(1.0, device=device), torch.tensor(-1.0, device=device))
    signed_prox = min_dist * side_flag

    # ── Channel 19: Impulse Strength ──────────────────────────────────────────
    impulse = torch.zeros_like(closes)
    impulse[10:] = torch.abs(closes[10:] - closes[:-10]) / (atr[10:] + eps)

    # ── Channel 20: Boundary Touch Density ────────────────────────────────────
    touch_top = (torch.abs(highs - r_high) < (0.1 * atr)).float()
    touch_bot = (torch.abs(lows - r_low) < (0.1 * atr)).float()
    touch_sum = touch_top + touch_bot
    
    if n >= 10:
        t_unfold = touch_sum.unfold(0, 10, 1)
        t_density_vals = torch.sum(t_unfold, dim=1) / 10.0
        t_density = torch.cat([torch.full((9,), t_density_vals[0], device=device), t_density_vals])
    else:
        t_density = torch.full((n,), torch.mean(touch_sum), device=device)

    # ── Channel 21: False Breakout Flag ───────────────────────────────────────
    # high[t] > rolling_high[t-1] AND close[t] <= rolling_high[t]
    rh_prev = torch.cat([r_high[0:1], r_high[:-1]])
    rl_prev = torch.cat([r_low[0:1], r_low[:-1]])
    
    fake_h = (highs > rh_prev) & (closes <= r_high)
    fake_l = (lows < rl_prev) & (closes >= r_low)
    false_breakout = (fake_h | fake_l).float()

    # ── Assembly ──────────────────────────────────────────────────────────────
    features = torch.stack([
        ohlc_norm[:, 0], ohlc_norm[:, 1], ohlc_norm[:, 2], ohlc_norm[:, 3], # 1-4
        body_size, c_range, u_wick, l_wick, direction,                    # 5-9
        vol_ratio, mom_3, slope,                                          # 10-12
        r_high_norm, r_low_norm,                                          # 13-14
        r_width_norm, r_stability,                                        # 15-16
        overlap,                                                          # 17
        signed_prox,                                                      # 18
        impulse,                                                          # 19
        t_density,                                                        # 20
        false_breakout                                                    # 21
    ], dim=1)
    
    return features

if __name__ == "__main__":
    # Test with synthetic data
    np.random.seed(42)
    data = np.cumsum(np.random.randn(100, 4), axis=0) + 100
    # ensure H >= O,C and L <= O,C
    data[:, 1] = np.max(data, axis=1) + 0.1
    data[:, 2] = np.min(data, axis=1) - 0.1
    
    features = build_features(data)
    print(f"Shape: {features.shape}")
    print(f"Min values:\n{features.min(dim=0).values}")
    print(f"Max values:\n{features.max(dim=0).values}")
    
    assert not torch.isnan(features).any(), "NaN detected!"
    assert not torch.isinf(features).any(), "Inf detected!"
    assert features.shape[1] == 21, "Channel count mismatch!"
    print("Validation Successful.")
