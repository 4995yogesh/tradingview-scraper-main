"""
DataFetcher — in-memory candle store for the multi-timeframe engine.

Optimizations:
  - collections.deque(maxlen) → O(1) append + automatic eviction (was O(n) slice)
  - max_candles bumped 100 → 300 (full session buffer on all timeframes)
  - get_latest_price() helper avoids redundant list scans
  - get_dataframe() pre-validates before building DataFrame
"""
from collections import deque
from typing import Dict, List, Optional
import pandas as pd

MAX_CANDLES = 300
TIMEFRAMES  = ["1m", "5m", "15m", "1H", "4H"]


class DataFetcher:
    def __init__(self):
        # deque gives O(1) append + O(1) auto-eviction — no more [-max_candles:] slicing
        self.history: Dict[str, deque] = {
            tf: deque(maxlen=MAX_CANDLES) for tf in TIMEFRAMES
        }

    def add_candle(self, timeframe: str, candle: dict) -> None:
        """
        Add a closed candle.
        Format: {timestamp, open, high, low, close, is_closed}
        If same timestamp as last candle, replaces it (live-tick update).
        """
        if timeframe not in self.history:
            return

        dq = self.history[timeframe]

        # Replace in-place if same bar (live tick update)
        if dq and dq[-1]["timestamp"] == candle["timestamp"]:
            dq[-1] = candle
        else:
            dq.append(candle)

    def get_candles(self, timeframe: str, limit: int = MAX_CANDLES) -> List[dict]:
        """Returns ascending list of the last `limit` candles for the timeframe."""
        if timeframe not in self.history:
            return []
        dq = self.history[timeframe]
        if limit >= len(dq):
            return list(dq)
        return list(dq)[-limit:]

    def get_latest_price(self, timeframe: str) -> Optional[float]:
        """Fast O(1) latest close price lookup."""
        dq = self.history.get(timeframe)
        if dq:
            return dq[-1].get("close")
        return None

    def get_dataframe(self, timeframe: str, limit: int = MAX_CANDLES) -> pd.DataFrame:
        """Returns a pandas DataFrame for the timeframe — validated before construction."""
        candles = self.get_candles(timeframe, limit)
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df


# Module-level singleton
fetcher_instance = DataFetcher()
