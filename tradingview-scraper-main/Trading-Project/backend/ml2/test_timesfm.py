"""
Smoke test for TimesFMPredictor.
Verifies:
  1. Model loads from Hugging Face (google/timesfm-1.0-200m)
  2. forecast_close_prices() returns an array of shape [horizon_len]
  3. Forecasted values are finite and in a plausible range
"""
import sys
import os

# Force JAX CPU backend
os.environ["JAX_PLATFORMS"] = "cpu"

# Make sure the ml2 directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

# ── 1. Build mock OHLC candles ──────────────────────────────────────────────
def make_mock_candles(n: int = 200, base_price: float = 100.0):
    rng = np.random.default_rng(42)
    candles = []
    price = base_price
    for i in range(n):
        change = rng.normal(0, 0.5)
        open_  = price
        close_ = price + change
        high_  = max(open_, close_) + abs(rng.normal(0, 0.2))
        low_   = min(open_, close_) - abs(rng.normal(0, 0.2))
        candles.append({
            'time':  i,
            'open':  round(open_,  4),
            'high':  round(high_,  4),
            'low':   round(low_,   4),
            'close': round(close_, 4),
        })
        price = close_
    return candles

# ── 2. Load predictor ────────────────────────────────────────────────────────
print("=" * 60)
print("TimesFM Smoke Test")
print("=" * 60)

print("\n[1/3] Loading TimesFMPredictor (context=512, horizon=50)...")
from timesfm_predictor import TimesFMPredictor
predictor = TimesFMPredictor(context_len=512, horizon_len=50)
print("      ✓ Predictor loaded.\n")

# ── 3. Run forecast on mock data ─────────────────────────────────────────────
print("[2/3] Running forecast on 200 mock candles...")
candles = make_mock_candles(n=200)
forecast = predictor.forecast_close_prices(candles)
print(f"      ✓ Forecast complete.")
print(f"      Shape  : {forecast.shape}  (expected ({predictor.horizon_len},))")
print(f"      Min    : {float(np.min(forecast)):.4f}")
print(f"      Max    : {float(np.max(forecast)):.4f}")
print(f"      Last   : {float(forecast[-1]):.4f}\n")

# ── 4. Assertions ────────────────────────────────────────────────────────────
print("[3/3] Validating forecast output...")
assert forecast.shape == (predictor.horizon_len,), \
    f"Shape mismatch: got {forecast.shape}"
assert np.all(np.isfinite(forecast)), "Forecast contains NaN or Inf"
assert float(np.max(forecast)) < 1e6,  "Forecast values unreasonably large"
assert float(np.min(forecast)) > -1e6, "Forecast values unreasonably small"
print("      ✓ Forecast assertions passed.\n")

# ── 5. Test Embedding and Extractor ──────────────────────────────────────────
print("[4/4] Testing get_embedding and TimeFMEmbeddingExtractor...")
embedding = predictor.get_embedding(candles)
print(f"      ✓ get_embedding complete.")
print(f"      Embedding shape: {embedding.shape} (expected (1280,))")
print(f"      Embedding norm : {float(np.linalg.norm(embedding)):.6f} (expected ~1.0)")

assert embedding.shape == (1280,), f"Embedding shape mismatch: got {embedding.shape}"
assert np.all(np.isfinite(embedding)), "Embedding contains NaN or Inf"
assert np.isclose(np.linalg.norm(embedding), 1.0, atol=1e-5), f"Embedding not L2-normalized: norm={np.linalg.norm(embedding)}"

from pattern_memory.embedding_extractor import TimeFMEmbeddingExtractor
extractor = TimeFMEmbeddingExtractor(predictor)
# Test window [50, 100] in 200 candles sequence
extractor_emb = extractor.get_embedding(candles, box_start_idx=100, box_end_idx=130, context_pre_candles=50)
assert extractor_emb is not None, "TimeFMEmbeddingExtractor returned None"
assert extractor_emb.shape == (1280,), f"Extractor embedding shape mismatch: got {extractor_emb.shape}"
assert np.isclose(np.linalg.norm(extractor_emb), 1.0, atol=1e-5), f"Extractor embedding not normalized: norm={np.linalg.norm(extractor_emb)}"
print("      ✓ Embedding and Extractor assertions passed.\n")

print("=" * 60)
print("RESULT: TimesFM integration smoke test PASSED ✓")
print("=" * 60)

