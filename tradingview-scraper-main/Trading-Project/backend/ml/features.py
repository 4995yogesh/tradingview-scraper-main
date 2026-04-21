"""
ml/features.py — Formation-time feature engineering pipeline.

FEATURE_VERSION = "v1"
18 features, all computed using ONLY candles <= box.time_end.
Leakage is enforced by assertion — will raise if violated.
"""

import math
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

FEATURE_VERSION = "v1"

FEATURE_NAMES = [
    # Geometry (3)
    "height_pct",
    "duration_bars",
    "range_compression",
    # Swing (5)
    "swings_inside",
    "swing_density",
    "dist_nearest_high_pct",
    "dist_nearest_low_pct",
    "swing_alignment",
    # Volatility (2)
    "atr_ratio",
    "std_inside_pct",
    # Volume (2)
    "volume_ratio",
    "volume_contraction",
    # Context (6)
    "prior_trend",
    "momentum_roc5",
    "dist_ema20_pct",
    "dist_ema50_pct",
    "price_percentile",
    "bars_since_breakout",
]

assert len(FEATURE_NAMES) == 18, "Feature count must be 18"


# ── Helper math ───────────────────────────────────────────────────────────────

def _ema(values: list, period: int) -> list:
    """Exponential Moving Average."""
    if not values or period <= 0:
        return values
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _atr(high: list, low: list, close: list, period: int = 14) -> float:
    """Average True Range over last `period` bars."""
    n = len(high)
    if n < 2:
        return 0.0
    trs = []
    for i in range(1, n):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)
    window = trs[-period:]
    return float(np.mean(window)) if window else 0.0


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den != 0 else default


# ── Main feature extractor ────────────────────────────────────────────────────

def extract_features(
    zone: dict,
    candles: list,
    swings: list,
) -> list:
    """
    Compute 18 formation-time features for a consolidation zone.

    Parameters
    ----------
    zone : dict
        {timeframe, timeStart (ms), timeEnd (ms), priceHigh, priceLow}
        symbol is optional, defaults to 'EURUSD'
    candles : list[dict]
        All raw DB candles (ts in seconds) for this symbol/timeframe.
        MUST include at least formation period candles.
    swings : list[dict]
        Swing markers: {type: 'high'|'low', price, time_ms, mitigated}

    Returns
    -------
    list of 18 Python floats (JSON-serializable).

    Raises
    ------
    AssertionError if future data leakage is detected.
    ValueError if not enough formation candles.
    """
    cutoff_ts = zone["timeEnd"] // 1000  # seconds
    price_high = float(zone["priceHigh"])
    price_low = float(zone["priceLow"])
    start_ts = zone["timeStart"] // 1000

    # ── LEAKAGE GUARD ─────────────────────────────────────────────────────────
    formation = sorted(
        [c for c in candles if int(c["ts"]) <= cutoff_ts],
        key=lambda c: int(c["ts"]),
    )
    assert formation, f"No formation candles at or before cutoff {cutoff_ts}"
    assert all(int(c["ts"]) <= cutoff_ts for c in formation), \
        "LEAKAGE: candle after cutoff found in formation set"

    formation_swings = [
        s for s in swings if int(s["time_ms"]) <= zone["timeEnd"]
    ]
    assert all(int(s["time_ms"]) <= zone["timeEnd"] for s in formation_swings), \
        "LEAKAGE: swing after zone.timeEnd found"

    if len(formation) < 5:
        raise ValueError(f"Insufficient formation candles: {len(formation)}")

    # Extract arrays
    hi = [float(c["high"]) for c in formation]
    lo = [float(c["low"]) for c in formation]
    cl = [float(c["close"]) for c in formation]
    op = [float(c["open"]) for c in formation]
    vol = [float(c.get("volume", 0)) for c in formation]
    ts_arr = [int(c["ts"]) for c in formation]

    # Find box candle indices
    box_indices = [
        i for i, ts in enumerate(ts_arr)
        if start_ts <= ts <= cutoff_ts
    ]
    if not box_indices:
        # Fall back to last 5 candles as box window
        box_indices = list(range(max(0, len(formation) - 5), len(formation)))

    # Mid price
    mid = (price_high + price_low) / 2.0

    # ── 1. GEOMETRY ───────────────────────────────────────────────────────────

    # height_pct: (H - L) / mid * 100
    height_pct = _safe_div((price_high - price_low) * 100.0, mid)

    # duration_bars
    duration_bars = float(len(box_indices))

    # range_compression: box_range / prior_20bar_range
    prior_idx_end = box_indices[0]
    prior_start = max(0, prior_idx_end - 20)
    prior_hi = max(hi[prior_start:prior_idx_end]) if prior_idx_end > prior_start else price_high
    prior_lo = min(lo[prior_start:prior_idx_end]) if prior_idx_end > prior_start else price_low
    prior_range = prior_hi - prior_lo
    box_range = price_high - price_low
    range_compression = _safe_div(box_range, prior_range, default=1.0)

    # ── 2. SWING FEATURES ─────────────────────────────────────────────────────

    inside_swings = [
        s for s in formation_swings
        if price_low <= float(s["price"]) <= price_high
        and start_ts * 1000 <= int(s["time_ms"]) <= zone["timeEnd"]
    ]
    swings_inside = float(len(inside_swings))
    swing_density = _safe_div(swings_inside, duration_bars)

    swing_highs = [
        float(s["price"]) for s in formation_swings
        if s["type"] == "high"
    ]
    swing_lows = [
        float(s["price"]) for s in formation_swings
        if s["type"] == "low"
    ]

    if swing_highs:
        nearest_high = min(swing_highs, key=lambda p: abs(p - mid))
        dist_nearest_high_pct = _safe_div(abs(nearest_high - mid) * 100.0, mid)
    else:
        dist_nearest_high_pct = 10.0  # sentinel: no swing highs

    if swing_lows:
        nearest_low = min(swing_lows, key=lambda p: abs(p - mid))
        dist_nearest_low_pct = _safe_div(abs(nearest_low - mid) * 100.0, mid)
    else:
        dist_nearest_low_pct = 10.0

    # swing_alignment: 0=none 1=hi_only 2=lo_only 3=both
    has_sh_inside = any(
        price_low <= float(s["price"]) <= price_high
        for s in formation_swings if s["type"] == "high"
    )
    has_sl_inside = any(
        price_low <= float(s["price"]) <= price_high
        for s in formation_swings if s["type"] == "low"
    )
    if has_sh_inside and has_sl_inside:
        swing_alignment = 3.0
    elif has_sh_inside:
        swing_alignment = 1.0
    elif has_sl_inside:
        swing_alignment = 2.0
    else:
        swing_alignment = 0.0

    # ── 3. VOLATILITY ─────────────────────────────────────────────────────────

    atr14 = _atr(hi, lo, cl, period=14)
    atr_ratio = _safe_div(box_range, atr14)

    box_closes = [cl[i] for i in box_indices]
    std_inside = float(np.std(box_closes)) if len(box_closes) > 1 else 0.0
    std_inside_pct = _safe_div(std_inside * 100.0, mid)

    # ── 4. VOLUME ─────────────────────────────────────────────────────────────

    box_vols = [vol[i] for i in box_indices]
    prior_vol_end = box_indices[0]
    prior_vol_start = max(0, prior_vol_end - 20)
    prior_vols = vol[prior_vol_start:prior_vol_end]

    avg_box_vol = float(np.mean(box_vols)) if box_vols else 0.0
    avg_prior_vol = float(np.mean(prior_vols)) if prior_vols else 0.0

    volume_ratio = _safe_div(avg_box_vol, avg_prior_vol, default=1.0)
    volume_contraction = 1.0 if (avg_prior_vol > 0 and avg_box_vol < avg_prior_vol * 0.8) else 0.0

    # ── 5. CONTEXT ────────────────────────────────────────────────────────────

    # prior_trend: slope sign of EMA10 over prior 10 bars before box
    ema10_all = _ema(cl, 10)
    ema_window_end = box_indices[0]
    ema_window_start = max(0, ema_window_end - 10)
    ema_slice = ema10_all[ema_window_start:ema_window_end]
    if len(ema_slice) >= 2:
        prior_trend = 1.0 if ema_slice[-1] > ema_slice[0] else -1.0
    else:
        prior_trend = 0.0

    # momentum_roc5: rate of change over 5 bars before box
    roc_end_idx = box_indices[0]
    roc_start_idx = max(0, roc_end_idx - 5)
    if roc_end_idx > 0 and cl[roc_start_idx] != 0:
        momentum_roc5 = _safe_div(
            (cl[roc_end_idx - 1] - cl[roc_start_idx]) * 100.0,
            cl[roc_start_idx]
        )
    else:
        momentum_roc5 = 0.0

    # dist_ema20_pct, dist_ema50_pct
    ema20_all = _ema(cl, 20)
    ema50_all = _ema(cl, 50)
    ema20_at_cutoff = ema20_all[-1] if ema20_all else mid
    ema50_at_cutoff = ema50_all[-1] if ema50_all else mid
    dist_ema20_pct = _safe_div((mid - ema20_at_cutoff) * 100.0, ema20_at_cutoff)
    dist_ema50_pct = _safe_div((mid - ema50_at_cutoff) * 100.0, ema50_at_cutoff)

    # price_percentile: percentile of mid in prior 252 bars
    lookback_cls = cl[max(0, len(cl) - 252):]
    below = sum(1 for c in lookback_cls if c < mid)
    price_percentile = _safe_div(below * 100.0, len(lookback_cls)) if lookback_cls else 50.0

    # bars_since_breakout: bars since last candle where close left prior box
    bars_since_breakout = 0.0
    if prior_idx_end > 0:
        prior_range_hi = max(hi[max(0, prior_idx_end - 20):prior_idx_end]) if prior_idx_end > 0 else price_high
        prior_range_lo = min(lo[max(0, prior_idx_end - 20):prior_idx_end]) if prior_idx_end > 0 else price_low
        for k in range(prior_idx_end - 1, -1, -1):
            if cl[k] > prior_range_hi or cl[k] < prior_range_lo:
                bars_since_breakout = float(prior_idx_end - k)
                break

    # ── Assemble ──────────────────────────────────────────────────────────────

    features = [
        # Geometry
        height_pct, duration_bars, range_compression,
        # Swing
        swings_inside, swing_density,
        dist_nearest_high_pct, dist_nearest_low_pct, swing_alignment,
        # Volatility
        atr_ratio, std_inside_pct,
        # Volume
        volume_ratio, volume_contraction,
        # Context
        prior_trend, momentum_roc5,
        dist_ema20_pct, dist_ema50_pct,
        price_percentile, bars_since_breakout,
    ]

    assert len(features) == 18, f"Feature count mismatch: {len(features)}"

    # Replace NaN/Inf with 0.0 (safety net)
    cleaned = []
    for f in features:
        if f is None or (isinstance(f, float) and (math.isnan(f) or math.isinf(f))):
            cleaned.append(0.0)
        else:
            cleaned.append(float(f))

    return cleaned
