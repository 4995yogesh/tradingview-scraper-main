"""
TimeFM Embedding Extractor — Phase 1
Extracts normalized pattern context window and computes TimeFM embedding.
"""
from __future__ import annotations

import logging
import numpy as np
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)


class TimeFMEmbeddingExtractor:
    """
    Extracts a window of candles surrounding a consolidation box,
    performs Z-score normalization on close prices,
    and calls TimesFMPredictor to get the L2-normalized 1280-dim embedding vector.
    """

    def __init__(self, predictor):
        """
        Args:
            predictor: TimesFMPredictor instance
        """
        self.predictor = predictor

    def get_embedding(
        self,
        candles: List[Dict[str, Any]],
        box_start_idx: int,
        box_end_idx: int,
        context_pre_candles: int = 50,
    ) -> Optional[np.ndarray]:
        """
        Extracts a window [start_idx - context_pre_candles, end_idx],
        Z-score normalizes close prices, and extracts embedding.

        Args:
            candles:             Full list of OHLC dicts (e.g. up to 512 candles)
            box_start_idx:       Index of box start in `candles`
            box_end_idx:         Index of box end in `candles`
            context_pre_candles: Number of candles before box start to include

        Returns:
            np.ndarray of shape (1280,) — L2-normalized float32 embedding, or None on error
        """
        if self.predictor is None:
            log.warning("[embedding] Predictor is None, cannot extract embedding")
            return None

        n = len(candles)
        if n == 0 or box_start_idx < 0 or box_end_idx >= n or box_start_idx > box_end_idx:
            log.error(
                f"[embedding] Invalid window range: start={box_start_idx}, end={box_end_idx}, n_candles={n}"
            )
            return None

        # Extract the window
        start = max(0, box_start_idx - context_pre_candles)
        # End is inclusive of box_end_idx
        end = box_end_idx + 1
        window = candles[start:end]

        if not window:
            return None

        # Z-score normalize close prices
        closes = np.array([float(c.get("close", 0.0)) for c in window], dtype=np.float32)
        mean = closes.mean()
        std = closes.std()
        std_val = std if std > 0.0 else 1.0

        # Create copy of window candles and replace close prices with Z-normalized values
        normalized_window = []
        for i, c in enumerate(window):
            normalized_c = dict(c)
            # Normalize close price
            normalized_c["close"] = float((closes[i] - mean) / std_val)
            normalized_window.append(normalized_c)

        try:
            emb = self.predictor.get_embedding(normalized_window)
            return emb
        except Exception as e:
            log.error(f"[embedding] TimeFM embedding extraction failed: {e}")
            return None
