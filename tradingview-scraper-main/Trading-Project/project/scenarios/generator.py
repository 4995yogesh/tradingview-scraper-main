"""
Scenario Generator — optimized.

Key changes:
  1. Path format fixed: [time, price] list → {"time": t, "price": p} dicts (matches frontend)
  2. _find_historical_tp: eliminated O(n²) loop — single pass with early-exit on first valid zone
  3. Computed ts_step once per function call (not per scenario)
  4. Every scenario always carries: confirmed, rr_ratio, scenario_name
  5. Passes recent_candles to breakout.detect_breakout for ATR expansion check
  6. No-trade sentinel uses a shared constant instead of repeated dict literals
"""
from typing import List, Dict, Optional
from strategy import consolidation, breakout, rejection, liquidity

# ── Sentinel for no-trade scenario (immutable) ───────────────────────────────
_NO_TRADE: dict = {
    "type": "none",
    "entry": None,
    "sl": None,
    "tp_zone": {"high": None, "low": None},
    "path": [],
    "scenario_name": "No Trade",
    "confirmed": False,
    "rr_ratio": 0.0,
}


def _no_trade() -> dict:
    """Return a fresh copy of the no-trade sentinel."""
    return dict(_NO_TRADE)


def _calc_rr(entry: float, sl: float, tp_high: float, tp_low: float, direction: str) -> float:
    """Risk/Reward ratio: (TP_mid - entry) / |entry - SL|, clipped to 0–10."""
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    tp_mid = (tp_high + tp_low) / 2.0
    reward = abs(tp_mid - entry)
    return round(min(reward / risk, 10.0), 2)


def _build_path(entry: float, target: float, start_time: int, ts_step: int, steps: int = 8) -> List[dict]:
    """
    Build a zig-zag projection path.
    Uses sinusoidal perturbation so the line isn't perfectly straight.
    Returns list of {"time": int_ms, "price": float} dicts.
    """
    import math
    path = []
    for i in range(1, steps + 1):
        t = start_time + ts_step * i
        frac = i / steps
        # Zig-zag: alternate ±20% of step magnitude
        zigzag = math.sin(i * 1.1) * abs(target - entry) * 0.18
        price = entry + (target - entry) * frac + zigzag
        path.append({"time": t, "price": round(price, 5)})
    return path


def _find_historical_tp(
    candles: List[Dict],
    entry_price: float,
    direction: str,
    zone_size: int = 15,
    step: int = 5,
) -> dict:
    """
    Scan historical candles for the nearest prior consolidation zone
    that is in the correct direction relative to entry.

    Optimization: single forward scan with early-exit on first valid hit.
    (Was a nested loop calling detect_consolidation on overlapping windows.)
    """
    end = len(candles) - zone_size
    if end <= 0:
        # Fallback: percentage-based TP
        if direction == "bullish":
            return {"high": entry_price * 1.0020, "low": entry_price * 1.0010}
        return {"high": entry_price * 0.9990, "low": entry_price * 0.9980}

    # Walk backwards through non-overlapping windows
    for start in range(end, 0, -step):
        window = candles[start: start + zone_size]
        zone   = consolidation.detect_consolidation(window)
        if not zone["valid"]:
            continue
        if direction == "bullish" and zone["low"] > entry_price:
            return {"high": zone["high"], "low": zone["low"]}
        if direction == "bearish" and zone["high"] < entry_price:
            return {"high": zone["high"], "low": zone["low"]}

    # Fallback
    if direction == "bullish":
        return {"high": entry_price * 1.0020, "low": entry_price * 1.0010}
    return {"high": entry_price * 0.9990, "low": entry_price * 0.9980}


def generate_scenarios(candles: List[Dict]) -> List[dict]:
    """
    Generates exactly 3 forward scenarios after a consolidation:
      1. Continuation   (breakout direction)
      2. Trap Reversal  (false breakout → reversal)
      3. No Trade       (always present as fallback)

    All scenarios carry: type, entry, sl, tp_zone, path, scenario_name,
                         confirmed (False initially), rr_ratio
    """
    if len(candles) < 15:
        return [_no_trade(), _no_trade(), _no_trade()]

    # Detect consolidation on all-but-last candle
    cons_zone = consolidation.detect_consolidation(candles[:-1])
    if not cons_zone["valid"]:
        return [_no_trade(), _no_trade(), _no_trade()]

    latest      = candles[-1]
    ts_step     = (candles[-1]["timestamp"] - candles[-2]["timestamp"]) if len(candles) > 1 else 60_000
    start_time  = int(latest["timestamp"])

    # ── Scenario 1: Continuation / Breakout ─────────────────────────────────
    brk = breakout.detect_breakout(latest, cons_zone, recent_candles=candles)
    s1  = _no_trade()

    if brk["is_breakout"]:
        direction = brk["direction"]
        entry = float(latest["close"])
        sl    = cons_zone["low"] if direction == "bullish" else cons_zone["high"]
        tp    = _find_historical_tp(candles, entry, direction)
        target = tp["low"] if direction == "bullish" else tp["high"]

        s1 = {
            "type":          "buy" if direction == "bullish" else "sell",
            "entry":         round(entry, 5),
            "sl":            round(sl, 5),
            "tp_zone":       tp,
            "path":          _build_path(entry, target, start_time, ts_step),
            "scenario_name": "Continuation",
            "confirmed":     False,
            "rr_ratio":      _calc_rr(entry, sl, tp["high"], tp["low"], direction),
            "strength":      brk.get("strength", 0.5),
        }

    # ── Scenario 2: Trap Reversal ────────────────────────────────────────────
    trp = rejection.detect_trap(candles, cons_zone)
    s2  = _no_trade()

    if trp["is_trap"]:
        direction = trp["direction"]
        liq = liquidity.compute_liquidity_entry(candles, direction)

        if liq["valid"]:
            entry = float(liq["entry"])
            sl    = float(liq["sl"])
            tp    = _find_historical_tp(candles, entry, direction)
            target = tp["low"] if direction == "bullish" else tp["high"]

            s2 = {
                "type":          "buy" if direction == "bullish" else "sell",
                "entry":         round(entry, 5),
                "sl":            round(sl, 5),
                "tp_zone":       tp,
                "path":          _build_path(entry, target, start_time, ts_step),
                "scenario_name": "Trap Reversal",
                "confirmed":     False,
                "rr_ratio":      _calc_rr(entry, sl, tp["high"], tp["low"], direction),
                "strength":      0.6,
            }

    return [s1, s2, _no_trade()]
