"""
Alert Manager — optimized.

Changes:
  - sent_alerts uses collections.deque(maxlen=500) → bounded FIFO ring,
    prevents unbounded RAM growth over long sessions
  - Rich Telegram message: includes RR ratio, strength, and TP zone
  - Confirmed-scenario alerts use a distinct icon and priority
"""
import asyncio
import logging
from collections import deque
from . import filters
from . import telegram

logger = logging.getLogger("AlertManager")

MAX_ALERT_HISTORY = 500   # Rolling window — oldest entries auto-evicted


class AlertManager:
    def __init__(self):
        # Deque-based ring buffer: bounded O(1) membership via set shadow
        self._alert_deque: deque = deque(maxlen=MAX_ALERT_HISTORY)
        self._alert_set:   set   = set()

    def _track(self, fingerprint: str) -> bool:
        """Return False if already seen; True and record if new."""
        if fingerprint in self._alert_set:
            return False
        # If deque is full, evict oldest fingerprint from the shadow set
        if len(self._alert_deque) == MAX_ALERT_HISTORY:
            evicted = self._alert_deque[0]
            self._alert_set.discard(evicted)
        self._alert_deque.append(fingerprint)
        self._alert_set.add(fingerprint)
        return True

    async def process_scenarios(
        self, timeframe: str, scenarios: list, timestamp: int
    ) -> None:
        """
        Process confirmed/actionable scenarios and fire Telegram alerts.
        Skips: invalid timeframes, out-of-hours, weak/no-trade scenarios, duplicates.
        """
        if not filters.is_valid_timeframe(timeframe):
            return
        if not filters.is_valid_time():
            return

        for scenario in scenarios:
            if not filters.is_valid_event(scenario):
                continue

            sig_type  = "Bullish" if scenario["type"] == "buy" else "Bearish"
            name      = scenario.get("scenario_name", "Unknown")
            confirmed = scenario.get("confirmed", False)
            rr        = scenario.get("rr_ratio", 0.0)
            strength  = scenario.get("strength", 0.0)

            fingerprint = f"{timeframe}_{timestamp}_{name}_{sig_type}"
            if not self._track(fingerprint):
                continue

            # ── Build rich message ──────────────────────────────────────────
            stars   = "★" if confirmed else "☆"
            icon    = "🚀" if name == "Continuation" else "⚠️"
            conf_lbl = " [CONFIRMED]" if confirmed else ""
            tp_zone  = scenario.get("tp_zone", {})
            tp_str   = (
                f"TP: {tp_zone.get('low', '?')} – {tp_zone.get('high', '?')}"
                if tp_zone.get("low") is not None
                else "TP: N/A"
            )

            message = (
                f"{icon} {stars} {name}{conf_lbl}\n"
                f"TF: {timeframe} | {sig_type}\n"
                f"Entry: {scenario.get('entry', '?')}\n"
                f"SL: {scenario.get('sl', '?')}\n"
                f"{tp_str}\n"
                f"RR: {rr:.2f}x  |  Strength: {strength:.0%}"
            )

            logger.info("Firing alert: %s", fingerprint)
            asyncio.create_task(telegram.send_alert(message))


alert_manager = AlertManager()
