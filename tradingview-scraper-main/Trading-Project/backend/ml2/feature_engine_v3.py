import torch
import numpy as np

def build_features(ohlc: np.ndarray) -> torch.Tensor:
    """
    Scale-Invariant Feature Engine v3
    
    Transformations:
    - Displacement: (Price - WindowStartClose) / ATR
    - Geometry: (High - Low) / ATR, (Close - Open) / ATR
    - Stability: Standardized volatility and touch density
    
    Result: Feature distributions are independent of absolute price (e.g. 1.08 vs 155).
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
    c_prev = torch.cat([closes[0:1], closes[:-1]])
    tr = torch.max(
        highs - lows,
        torch.max(torch.abs(highs - c_prev), torch.abs(lows - c_prev))
    )
    atr_kernel = torch.ones(1, 1, 14, device=device) / 14
    atr = torch.nn.functional.conv1d(
        tr.view(1, 1, -1), atr_kernel, padding=13
    ).view(-1)[:n]
    
    if n > 13:
        warmup = torch.cumsum(tr[:13], dim=0) / torch.arange(1, 14, device=device)
        atr[:13] = warmup
    else:
        atr[:] = torch.mean(tr) if n > 0 else eps
    atr = torch.clamp(atr, min=eps)

    # Reference Price: Close of the first candle in the window
    ref_price = closes[0]

    # ── Channels 1-4: OHLC Displacement ──────────────────────────────────────
    # Scale Invariance: Measuring displacement in volatility (ATR) units
    ohlc_rel = (t_ohlc - ref_price) / atr.view(-1, 1)
    
    # ── Channels 5-9: Geometry (Already Scale-Invariant) ─────────────────────
    body_size = (closes - opens) / atr  # Signed to retain direction
    c_range   = (highs - lows) / atr
    u_wick    = (highs - torch.max(opens, closes)) / atr
    l_wick    = (torch.min(opens, closes) - lows) / atr
    direction = torch.sign(closes - opens)
    
    # ── Channels 10-12: Dynamics ─────────────────────────────────────────────
    r_kernel = torch.ones(1, 1, 14, device=device) / 14
    sma_range = torch.nn.functional.conv1d(
        (highs - lows).view(1, 1, -1), r_kernel, padding=13
    ).view(-1)[:n]
    if n > 13:
        warmup_range = torch.cumsum((highs - lows)[:13], dim=0) / torch.arange(1, 14, device=device)
        sma_range[:13] = warmup_range
    else:
        sma_range[:] = torch.mean(highs - lows)
    vol_ratio = (highs - lows) / (sma_range + eps)
    
    mom_3 = torch.zeros_like(closes)
    mom_3[3:] = (closes[3:] - closes[:-3]) / atr[3:]
    
    slope = torch.zeros_like(closes)
    slope[10:] = (closes[10:] - closes[:-10]) / (10 * atr[10:])

    # ── Channels 13-14: Rolling High/Low Relative ────────────────────────────
    if n >= 10:
        h_unfold = highs.unfold(0, 10, 1)
        l_unfold = lows.unfold(0, 10, 1)
        r_high_vals = torch.max(h_unfold, dim=1).values
        r_low_vals  = torch.min(l_unfold, dim=1).values
        prefix_h = torch.cummax(highs[:9], dim=0).values
        prefix_l = torch.cummin(lows[:9], dim=0).values
        r_high = torch.cat([prefix_h, r_high_vals])
        r_low  = torch.cat([prefix_l, r_low_vals])
    else:
        r_high = torch.cummax(highs, dim=0).values
        r_low  = torch.cummin(lows, dim=0).values
    
    r_high_rel = (r_high - ref_price) / atr
    r_low_rel  = (r_low - ref_price) / atr

    # ── Channels 15-16: Range Meta ────────────────────────────────────────────
    r_width = (r_high - r_low)
    r_width_norm = r_width / atr
    
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
    min_dist = torch.min(dist_top, dist_bot)
    side_flag = torch.where(dist_top < dist_bot, torch.tensor(1.0, device=device), torch.tensor(-1.0, device=device))
    signed_prox = min_dist * side_flag

    # ── Channel 19: Impulse Strength ──────────────────────────────────────────
    impulse = torch.zeros_like(closes)
    impulse[10:] = torch.abs(closes[10:] - closes[:-10]) / (atr[10:] + eps)

    # Channel 20: Boundary Touch Density
    threshold = torch.min(0.1 * atr, 0.2 * r_width + eps)
    touch_top = (torch.abs(highs - r_high) < threshold).float()
    touch_bot = (torch.abs(lows - r_low) < threshold).float()
    touch_sum = touch_top + touch_bot
    if n >= 10:
        t_unfold = touch_sum.unfold(0, 10, 1)
        t_density_vals = torch.sum(t_unfold, dim=1) / 10.0
        t_density = torch.cat([torch.full((9,), t_density_vals[0], device=device), t_density_vals])
    else:
        t_density = torch.full((n,), torch.mean(touch_sum), device=device)

    # ── Channel 21: False Breakout Flag ───────────────────────────────────────
    rh_prev = torch.cat([r_high[0:1], r_high[:-1]])
    rl_prev = torch.cat([r_low[0:1], r_low[:-1]])
    fake_h = (highs > rh_prev) & (closes <= rh_prev)
    fake_l = (lows < rl_prev) & (closes >= rl_prev)
    false_breakout = (fake_h | fake_l).float()

    # ── Assembly ──────────────────────────────────────────────────────────────
    features = torch.stack([
        ohlc_rel[:, 0], ohlc_rel[:, 1], ohlc_rel[:, 2], ohlc_rel[:, 3], # 1-4 (Rel Displacement)
        body_size, c_range, u_wick, l_wick, direction,                  # 5-9 (Local Geometry)
        vol_ratio, mom_3, slope,                                        # 10-12 (Dynamics)
        r_high_rel, r_low_rel,                                          # 13-14 (Rel Boundaries)
        r_width_norm, r_stability,                                      # 15-16 (Range Meta)
        overlap,                                                        # 17
        signed_prox,                                                    # 18
        impulse,                                                        # 19
        t_density,                                                      # 20
        false_breakout                                                  # 21
    ], dim=1)
    
    return features

if __name__ == "__main__":
    # Smoke test
    data = np.cumsum(np.random.randn(50, 4), axis=0) + 100
    data[:, 1] = np.max(data, axis=1) + 0.1
    data[:, 2] = np.min(data, axis=1) - 0.1
    f = build_features(data)
    print(f"v3 Features Shape: {f.shape}")
    print(f"Sample (First Close Rel): {f[0, 3].item():.4f} (Expected: 0.0)")
    assert abs(f[0, 3].item()) < 1e-6
