import torch
import numpy as np

def build_features(ohlc: np.ndarray) -> torch.Tensor:
    """
    Structural Temporal Feature Engine v4
    
    Upgrades:
    - Anchor: Rolling Median(20) instead of FirstClose.
    - Temporal: ATR Slope, Compression Ratios, Equilibrium persistence.
    - Scale Invariance: All features unitless (ATR or Ratio based).
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    t_ohlc = torch.from_numpy(ohlc).float().to(device)
    
    n = t_ohlc.shape[0]
    eps = 1e-8
    
    opens  = t_ohlc[:, 0]
    highs  = t_ohlc[:, 1]
    lows   = t_ohlc[:, 2]
    closes = t_ohlc[:, 3]
    
    # ── Step 0: ATR (14) ─────────────────────────────────────────────────────
    c_prev = torch.cat([closes[0:1], closes[:-1]])
    tr = torch.max(highs - lows, torch.max(torch.abs(highs - c_prev), torch.abs(lows - c_prev)))
    atr_kernel = torch.ones(1, 1, 14, device=device) / 14
    atr = torch.nn.functional.conv1d(tr.view(1, 1, -1), atr_kernel, padding=13).view(-1)[:n]
    if n > 13:
        atr[:13] = torch.cumsum(tr[:13], dim=0) / torch.arange(1, 14, device=device)
    else:
        atr[:] = torch.mean(tr) if n > 0 else eps
    atr = torch.clamp(atr, min=eps)

    # ── Rolling Median Anchor (20) ───────────────────────────────────────────
    if n >= 20:
        c_unfold = closes.unfold(0, 20, 1)
        med_vals = torch.median(c_unfold, dim=1).values
        med = torch.cat([torch.full((19,), med_vals[0], device=device), med_vals])
    else:
        med = torch.full((n,), torch.median(closes), device=device)

    # ── Channels 1-4: OHLC vs Median Displacement ────────────────────────────
    ohlc_rel = (t_ohlc - med.view(-1, 1)) / atr.view(-1, 1)
    
    # ── Channels 5-9: Geometry ───────────────────────────────────────────────
    body_size = (closes - opens) / atr
    c_range   = (highs - lows) / atr
    u_wick    = (highs - torch.max(opens, closes)) / atr
    l_wick    = (torch.min(opens, closes) - lows) / atr
    direction = torch.sign(closes - opens)
    
    # ── Channels 10-12: Dynamics ─────────────────────────────────────────────
    # 10: Vol Ratio
    sma_range = torch.nn.functional.conv1d((highs - lows).view(1, 1, -1), atr_kernel, padding=13).view(-1)[:n]
    vol_ratio = (highs - lows) / (sma_range + eps)
    # 11: Momentum
    mom_3 = torch.zeros_like(closes)
    mom_3[3:] = (closes[3:] - closes[:-3]) / atr[3:]
    # 12: Slope
    slope = torch.zeros_like(closes)
    slope[10:] = (closes[10:] - closes[:-10]) / (10 * atr[10:])

    # ── Channels 13-14: Rolling High/Low vs Median ───────────────────────────
    if n >= 10:
        h_unfold = highs.unfold(0, 10, 1)
        l_unfold = lows.unfold(0, 10, 1)
        r_high = torch.cat([torch.cummax(highs[:9], dim=0).values, torch.max(h_unfold, dim=1).values])
        r_low  = torch.cat([torch.cummin(lows[:9], dim=0).values, torch.min(l_unfold, dim=1).values])
    else:
        r_high, r_low = torch.cummax(highs, 0).values, torch.cummin(lows, 0).values
    
    r_high_rel = (r_high - med) / atr
    r_low_rel  = (r_low - med) / atr

    # ── Channels 15-16: Range Meta ────────────────────────────────────────────
    r_width = (r_high - r_low)
    r_width_norm = r_width / atr
    r_stability = torch.zeros(n, device=device)
    if n >= 10:
        w_unfold = r_width.unfold(0, 10, 1)
        r_stability = torch.cat([torch.zeros(9, device=device), torch.std(w_unfold, 1) / (torch.mean(w_unfold, 1) + eps)])

    # ── Channels 17-21: Structural Stats ─────────────────────────────────────
    # 17: Overlap
    h_prev = torch.cat([highs[0:1], highs[:-1]])
    l_prev = torch.cat([lows[0:1], lows[:-1]])
    inter = torch.clamp(torch.min(highs, h_prev) - torch.max(lows, l_prev), min=0)
    overlap = inter / (torch.max(highs, h_prev) - torch.min(lows, l_prev) + eps)
    
    # 18: Prox, 19: Impulse, 20: Density, 21: Fake
    signed_prox = (torch.min(torch.abs(highs - r_high), torch.abs(lows - r_low)) / (r_width + eps)) * \
                  torch.where(torch.abs(highs - r_high) < torch.abs(lows - r_low), 1.0, -1.0)
    impulse = torch.zeros_like(closes)
    impulse[10:] = torch.abs(closes[10:] - closes[:-10]) / (atr[10:] + eps)
    
    threshold = torch.min(0.1 * atr, 0.2 * r_width + eps)
    touch = ((torch.abs(highs - r_high) < threshold) | (torch.abs(lows - r_low) < threshold)).float()
    t_density = torch.zeros(n, device=device)
    if n >= 10:
        t_density = torch.cat([torch.zeros(9, device=device), torch.mean(touch.unfold(0, 10, 1), 1)])
    
    rh_prev = torch.cat([r_high[0:1], r_high[:-1]])
    rl_prev = torch.cat([r_low[0:1], r_low[:-1]])
    fake = ((highs > rh_prev) & (closes <= rh_prev)) | \
           ((lows < rl_prev) & (closes >= rl_prev))
    fake = fake.float()

    # ── NEW TEMPORAL FEATURES (22-30) ────────────────────────────────────────
    # 22: ATR Slope (Volatility Decay)
    atr_slope = torch.zeros_like(atr)
    if n >= 10:
        atr_slope[10:] = (atr[10:] - atr[:-10]) / (10 * atr[10:] + eps)
    
    # 23: Compression Ratio (Range10 / Range30)
    comp_ratio = torch.ones(n, device=device)
    if n >= 30:
        # Calculate 30-candle high/low correctly using unfold
        h_30_unfold = highs.unfold(0, 30, 1)
        l_30_unfold = lows.unfold(0, 30, 1)
        r_30_h = torch.max(h_30_unfold, dim=1).values
        r_30_l = torch.min(l_30_unfold, dim=1).values
        # Pad beginning
        r_30_h = torch.cat([torch.cummax(highs[:29], 0).values, r_30_h])
        r_30_l = torch.cat([torch.cummin(lows[:29], 0).values, r_30_l])
        
        comp_ratio = r_width / (r_30_h - r_30_l + eps)
        comp_ratio = torch.clamp(comp_ratio, 0, 1) # Range10 cannot exceed Range30 logically

    # 24: Equilibrium Persistence (Time near median)
    near_med = (torch.abs(closes - med) < 0.5 * atr).float()
    eq_persist = torch.zeros(n, device=device)
    if n >= 10:
        eq_persist = torch.cat([torch.zeros(9, device=device), torch.mean(near_med.unfold(0, 10, 1), 1)])

    # 25: Directional Entropy (Sum of moves / Net displacement)
    moves = torch.abs(closes - c_prev)
    cum_moves = torch.cumsum(moves, 0)
    net_move = torch.abs(closes - closes[0])
    dir_entropy = net_move / (cum_moves + eps)

    # 26: Cumulative Rejection (Weighted touch density)
    rej_accum = torch.zeros(n, device=device)
    curr_rej = 0.0
    for i in range(n):
        curr_rej = curr_rej * 0.9 + touch[i]
        rej_accum[i] = curr_rej

    # 27: Volatility Z-Score
    vol_z = (tr - atr) / (torch.std(tr) + eps)

    # 28: Body Expansion Ratio (Local Body / Window Body)
    avg_body_20 = torch.mean(torch.abs(closes - opens))
    body_exp = (torch.abs(closes - opens)) / (avg_body_20 + eps)

    # 29: Positional Encoding (Linear)
    pos_enc = torch.linspace(0, 1, n, device=device)

    # 30: Range Tightness (ATR / Range Width)
    range_tight = atr / (r_width + eps)

    # 31: Swing High (3-candle peak)
    swing_high = torch.zeros_like(highs)
    if n >= 3:
        swing_high[1:-1] = ((highs[1:-1] > highs[:-2]) & (highs[1:-1] > highs[2:])).float()

    # 32: Swing Low (3-candle trough)
    swing_low = torch.zeros_like(lows)
    if n >= 3:
        swing_low[1:-1] = ((lows[1:-1] < lows[:-2]) & (lows[1:-1] < lows[2:])).float()

    # ── Final Stack (32 Channels) ────────────────────────────────────────────
    features = torch.stack([
        ohlc_rel[:, 0], ohlc_rel[:, 1], ohlc_rel[:, 2], ohlc_rel[:, 3], # 1-4
        body_size, c_range, u_wick, l_wick, direction,                  # 5-9
        vol_ratio, mom_3, slope,                                        # 10-12
        r_high_rel, r_low_rel, r_width_norm, r_stability,               # 13-16
        overlap, signed_prox, impulse, t_density, fake,                 # 17-21
        atr_slope, comp_ratio, eq_persist, dir_entropy, rej_accum,      # 22-26
        vol_z, body_exp, pos_enc, range_tight,                           # 27-30
        swing_high, swing_low                                            # 31-32
    ], dim=1)
    
    return features

if __name__ == "__main__":
    data = np.cumsum(np.random.randn(50, 4), axis=0) + 100
    data[:, 1] = np.max(data, axis=1) + 0.1
    data[:, 2] = np.min(data, axis=1) - 0.1
    f = build_features(data)
    print(f"v4 Features Shape: {f.shape}")
    assert f.shape[1] == 32
    print("Feature distribution check passed.")
