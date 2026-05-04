import sys
import os
import json
import numpy as np
import torch

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from inference import predict, model_a
from model_a import predict_heatmap
from feature_engine_v2_1 import build_features

# Mock candles
mock_candles = []
for i in range(50):
    mock_candles.append({
        'time': 1700000000 + i * 900000,
        'open': 1.1000,
        'high': 1.1005,
        'low': 1.0995,
        'close': 1.1000,
    })

# Force a consolidation pattern
for i in range(20, 30):
    mock_candles[i]['high'] = 1.1010
    mock_candles[i]['low'] = 1.0990

raw_ohlc = np.array([[c['open'], c['high'], c['low'], c['close']] for c in mock_candles], dtype=np.float32)
features = build_features(raw_ohlc).cpu().numpy()

if model_a:
    heatmap = predict_heatmap(model_a, features)
    print(f"Heatmap max: {heatmap.max():.4f}")
    print(f"Heatmap min: {heatmap.min():.4f}")
    print(f"Heatmap mean: {heatmap.mean():.4f}")
    print(f"Heatmap values: {heatmap}")
else:
    print("Model A NOT LOADED")

result = predict(mock_candles)
if result:
    print("Prediction SUCCESS")
else:
    print("Prediction FAILED (Expected if heatmap < 0.5)")
