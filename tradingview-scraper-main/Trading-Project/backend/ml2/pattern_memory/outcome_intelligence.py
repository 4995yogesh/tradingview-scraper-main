"""
Outcome Intelligence Engine — Phase 5
Computes weighted probability statistics from top-K historical pattern matches.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

# ── Thresholds (override per asset class) ─────────────────────────────────────
FOREX_THRESHOLD = 0.0015          # 15 pips — bullish/bearish classification
STOCK_THRESHOLD = 0.005           # 50 bps
DEFAULT_THRESHOLD = FOREX_THRESHOLD


@dataclass
class PatternIntelligence:
    """Complete intelligence report for a detected pattern."""

    # Directional probabilities (sum to ~1.0)
    bullish_probability: float = 0.0
    bearish_probability: float = 0.0
    neutral_probability: float = 0.0

    # Move statistics
    average_move:     float = 0.0   # weighted abs return at horizon
    average_drawdown: float = 0.0   # weighted MAE (ATR units)

    # Trade statistics
    historical_win_rate: float = 0.0   # unweighted — more interpretable
    expectancy:          float = 0.0   # win_rate * avg_win - loss_rate * avg_loss

    # Top matching patterns (compact dicts, no embeddings)
    similar_patterns: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    n_matches:       int  = 0
    n_with_outcomes: int  = 0
    confidence:      str  = "LOW"    # "HIGH" (>=30), "MEDIUM" (>=10), "LOW"
    horizon_candles: int  = 20
    threshold_used:  float = DEFAULT_THRESHOLD
    weighted:        bool = True

    # Extra breakout stats
    breakout_up_rate:    float = 0.0
    breakout_down_rate:  float = 0.0
    avg_time_to_breakout: Optional[float] = None
    fakeout_rate:        float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bullish_probability":  round(self.bullish_probability, 4),
            "bearish_probability":  round(self.bearish_probability, 4),
            "neutral_probability":  round(self.neutral_probability, 4),
            "average_move":         round(self.average_move, 6),
            "average_drawdown":     round(self.average_drawdown, 4) if self.average_drawdown else None,
            "historical_win_rate":  round(self.historical_win_rate, 4),
            "expectancy":           round(self.expectancy, 6),
            "n_matches":            self.n_matches,
            "n_with_outcomes":      self.n_with_outcomes,
            "confidence":           self.confidence,
            "horizon_candles":      self.horizon_candles,
            "breakout_up_rate":     round(self.breakout_up_rate, 4),
            "breakout_down_rate":   round(self.breakout_down_rate, 4),
            "avg_time_to_breakout": round(self.avg_time_to_breakout, 1) if self.avg_time_to_breakout else None,
            "fakeout_rate":         round(self.fakeout_rate, 4),
            "similar_patterns":     self.similar_patterns,
        }


class OutcomeIntelligence:
    """
    Computes weighted outcome statistics from top-K FAISS matches.
    Designed to work with PatternRecord objects from pattern_db.py.
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold

    def compute(
        self,
        matches,               # List[PatternRecord]
        similarity_scores,     # List[float]  (cosine similarities, descending)
        horizon: int = 20,
        top_display: int = 10,
    ) -> PatternIntelligence:
        """
        Args:
            matches:           PatternRecord objects from PatternMemoryDB.get_patterns_by_ids()
            similarity_scores: Cosine similarity scores aligned with matches
            horizon:           Candle horizon for return classification (20 or 50)
            top_display:       Number of similar patterns to include in the report

        Returns:
            PatternIntelligence with all computed statistics
        """
        n_total = len(matches)

        # Filter to patterns that have outcome data
        scored = [
            (rec, score)
            for rec, score in zip(matches, similarity_scores)
            if self._get_return(rec, horizon) is not None
        ]

        if not scored:
            return PatternIntelligence(
                n_matches=n_total,
                n_with_outcomes=0,
                confidence="LOW",
                horizon_candles=horizon,
                similar_patterns=[m.to_summary() for m in matches[:top_display]],
            )

        recs   = [s[0] for s in scored]
        scores = np.array([s[1] for s in scored], dtype=np.float64)

        # ── Weights — linear (not softmax to preserve similarity intuition) ────
        weights = scores / scores.sum()

        # ── Returns ───────────────────────────────────────────────────────────
        returns = np.array([self._get_return(r, horizon) for r in recs], dtype=np.float64)

        threshold = self.threshold
        bullish = returns >  threshold
        bearish = returns < -threshold
        neutral = ~bullish & ~bearish

        bullish_prob = float(np.dot(weights, bullish))
        bearish_prob = float(np.dot(weights, bearish))
        neutral_prob = float(np.dot(weights, neutral))

        # Avg absolute move (weighted)
        avg_move = float(np.dot(weights, np.abs(returns)))

        # Avg MAE (weighted, ATR units) — use 0.0 if MAE not available
        maes = np.array([r.mae if r.mae is not None else 0.0 for r in recs])
        avg_drawdown = float(np.dot(weights, maes))

        # ── Win rate — unweighted (more interpretable for traders) ────────────
        win_rate = float(bullish.sum() / len(recs))

        # Expectancy
        avg_win  = float(returns[bullish].mean()) if bullish.any() else 0.0
        avg_loss = float(abs(returns[bearish].mean())) if bearish.any() else 0.0
        expectancy = win_rate * avg_win - (1.0 - win_rate) * avg_loss

        # ── Breakout direction distribution (unweighted counts) ───────────────
        bk_up   = sum(1 for r in recs if r.breakout_direction == "UP")
        bk_down = sum(1 for r in recs if r.breakout_direction == "DOWN")
        n = len(recs)
        bk_up_rate   = bk_up   / n
        bk_down_rate = bk_down / n

        # Avg time to breakout
        ttb = [r.time_to_breakout for r in recs if r.time_to_breakout is not None]
        avg_ttb = float(np.mean(ttb)) if ttb else None

        # Fakeout rate (confirmed=0 among those with a breakout)
        has_bk = [r for r in recs if r.breakout_direction in ("UP", "DOWN")]
        fakeouts = sum(1 for r in has_bk if r.breakout_confirmed == 0)
        fakeout_rate = (fakeouts / len(has_bk)) if has_bk else 0.0

        # ── Confidence ────────────────────────────────────────────────────────
        n_with = len(recs)
        confidence = "HIGH" if n_with >= 30 else "MEDIUM" if n_with >= 10 else "LOW"

        # ── Top display patterns (ranked by similarity) ───────────────────────
        top_matches = [r.to_summary() for r in recs[:top_display]]
        # Annotate with similarity score
        for i, d in enumerate(top_matches):
            d["similarity_score"] = round(float(scored[i][1]), 4)

        return PatternIntelligence(
            bullish_probability = bullish_prob,
            bearish_probability = bearish_prob,
            neutral_probability = neutral_prob,
            average_move        = avg_move,
            average_drawdown    = avg_drawdown,
            historical_win_rate = win_rate,
            expectancy          = expectancy,
            similar_patterns    = top_matches,
            n_matches           = n_total,
            n_with_outcomes     = n_with,
            confidence          = confidence,
            horizon_candles     = horizon,
            threshold_used      = threshold,
            weighted            = True,
            breakout_up_rate    = bk_up_rate,
            breakout_down_rate  = bk_down_rate,
            avg_time_to_breakout= avg_ttb,
            fakeout_rate        = fakeout_rate,
        )

    @staticmethod
    def _get_return(rec, horizon: int) -> Optional[float]:
        """Get the return at the given horizon from a PatternRecord."""
        field_map = {10: "future_return_10", 20: "future_return_20",
                     50: "future_return_50", 100: "future_return_100"}
        attr = field_map.get(horizon, "future_return_20")
        return getattr(rec, attr, None)
