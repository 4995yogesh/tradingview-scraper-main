import torch
import torch.nn as nn
import numpy as np
import threading
import logging
import os
import json
import datetime

MODEL_VERSION = "nn_v1"
_nn_model = None
_nn_lock = threading.RLock()

class ConsolidationCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(4, 32, kernel_size=3, padding=1),
            nn.BatchNorm1d(32), nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64), nn.ReLU()
        )
        self.fc = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 50, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 4)
        )
    def forward(self, x):
        x = x.transpose(1, 2)  # (N, 4, seq_len)
        x = self.conv(x)        # (N, 64, seq_len)
        return self.fc(x)       # (N, 4)

def load_nn_model() -> None:
    global _nn_model
    with _nn_lock:
        if _nn_model is None:
            model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'models', 'consolidation_nn.pt')
            _nn_model = ConsolidationCNN()
            _nn_model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
            _nn_model.eval()

def predict_box(ohlc_candles: list) -> dict | None:
    try:
        if not is_nn_ready():
            return None
        if len(ohlc_candles) == 0:
            return None
        sequence_length = 50
        if len(ohlc_candles) >= sequence_length:
            candles = ohlc_candles[-sequence_length:]
        else:
            pad = [ohlc_candles[0]] * (sequence_length - len(ohlc_candles))
            candles = pad + ohlc_candles
            
        candles = [{k: v for k, v in candle.items() if k in ['open', 'high', 'low', 'close']} for candle in candles]
        candles = np.array([[candle['open'], candle['high'], candle['low'], candle['close']] for candle in candles])
        
        window_min = np.min(candles)
        window_max = np.max(candles)
        window_range = max(1e-9, window_max - window_min)
        
        candles = (candles - window_min) / window_range
        candles = np.expand_dims(candles, axis=0)
        
        with torch.no_grad():
            input_tensor = torch.tensor(candles, dtype=torch.float32)
            output = _nn_model(input_tensor)
            output = output.numpy()[0]
            
        start_idx_norm, end_idx_norm, price_high_norm, price_low_norm = output
        start_idx = max(0, min(int(round(start_idx_norm * sequence_length)), len(ohlc_candles) - 1))
        end_idx = max(0, min(int(round(end_idx_norm * sequence_length)), len(ohlc_candles) - 1))
        
        price_high = float((price_high_norm * window_range) + window_min)
        price_low = float((price_low_norm * window_range) + window_min)
        confidence = float(1 / (1 + abs(price_high - price_low)))
        confidence = max(0.0, min(1.0, confidence))
        time_start = _to_unix(ohlc_candles[start_idx]['time'])
        time_end = _to_unix(ohlc_candles[end_idx]['time'])
        return {
            'timeStart': time_start,
            'timeEnd': time_end,
            'priceHigh': price_high,
            'priceLow': price_low,
            'confidence': confidence,
            'model_version': MODEL_VERSION
        }
    except Exception as e:
        logging.error(f"Error in predict_box: {e}")
        return None

def is_nn_ready() -> bool:
    with _nn_lock:
        return _nn_model is not None

def _to_unix(t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    elif isinstance(t, str):
        return datetime.datetime.fromisoformat(t).timestamp()
    else:
        raise ValueError("Invalid time format")