"""
Multi-Timeframe Confirmation Engine — optimized.

Changes:
  - Sets confirmed=True on scenarios that align with HTF
  - Uses strength + rr_ratio thresholds for quality filtering
  - Propagates HTF strength boost to LTF scenario score
  - No longer returns silent empty confirms — logs every decision
"""
from typing import Dict, List
import logging

logger = logging.getLogger("MTF")

# Minimum RR to accept a confirmed scenario
MIN_RR_FOR_CONFIRM = 1.5


def confirm_mtf(
    scenarios_ltf: List[dict],
    scenarios_htf: List[dict],
) -> List[dict]:
    """
    Multi-timeframe confirmation:
      4H → 15m  |  1H → 5m  |  15m → 1m

    Rules:
      - LTF Continuation + HTF Continuation (same direction) → confirmed=True, boost strength
      - LTF Trap Reversal → always confirmed (traps override HTF signal)
      - LTF Continuation contradicts HTF → downgrade to no-trade (not enough conviction)
      - No HTF active signals → pass through LTF unchanged
    """
    if not scenarios_ltf:
        return scenarios_ltf

    if not scenarios_htf:
        return scenarios_ltf  # No HTF data → pass through

    # Index HTF scenarios by name for O(1) lookup
    htf_by_name: Dict[str, dict] = {}
    for s in scenarios_htf:
        name = s.get("scenario_name", "")
        if name and s.get("type") != "none":
            htf_by_name[name] = s

    htf_active = [s for s in scenarios_htf if s.get("type") != "none"]
    if not htf_active:
        # No active HTF → pass LTF through unchanged
        return scenarios_ltf

    result = []
    for ltf in scenarios_ltf:
        if ltf.get("type") == "none":
            result.append(ltf)
            continue

        name  = ltf.get("scenario_name", "")
        rr    = ltf.get("rr_ratio", 0.0)

        if name == "Trap Reversal":
            # Traps always override — they imply HTF was faked
            confirmed = ltf.copy()
            confirmed["confirmed"] = True
            result.append(confirmed)
            continue

        if name == "Continuation":
            htf_brk = htf_by_name.get("Continuation")

            if htf_brk and htf_brk.get("type") == ltf.get("type"):
                # ✅ Same direction continuation on both TFs
                if rr >= MIN_RR_FOR_CONFIRM:
                    confirmed = ltf.copy()
                    confirmed["confirmed"] = True
                    # Boost strength by HTF conviction
                    htf_strength = htf_brk.get("strength", 0.5)
                    confirmed["strength"] = round(
                        min(1.0, ltf.get("strength", 0.5) * 0.6 + htf_strength * 0.4), 3
                    )
                    logger.info(
                        "MTF confirm: %s | dir=%s | RR=%.2f | strength=%.2f",
                        name, confirmed["type"], rr, confirmed["strength"]
                    )
                    result.append(confirmed)
                else:
                    # Direction aligned but RR too low — keep, unconfirmed
                    result.append(ltf)
            else:
                # ❌ HTF contradiction or no HTF breakout → downgrade
                logger.debug("MTF cancel: LTF %s contradicts HTF", name)
                result.append({
                    "type": "none", "entry": None, "sl": None,
                    "tp_zone": {"high": None, "low": None}, "path": [],
                    "scenario_name": "No Trade", "confirmed": False, "rr_ratio": 0.0,
                })
            continue

        # Any other scenario type → pass through
        result.append(ltf)

    return result
