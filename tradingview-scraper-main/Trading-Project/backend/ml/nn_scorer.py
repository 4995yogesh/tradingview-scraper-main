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
            nn.Conv1d(5, 32, kernel_size=3, padding=1),
            nn.BatchNorm1d(32), nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64), nn.ReLU()
        )
        self.fc = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 100, 128),
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
            model_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'models', 'consolidation_nn.pt')
            _nn_model = ConsolidationCNN()
            _nn_model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
            _nn_model.eval()

def predict_box(ohlc_candles: list) -> dict | None:
    try:
        if not is_nn_ready():
            return None
        if len(ohlc_candles) == 0:
            return None
        sequence_length = 100
        if len(ohlc_candles) >= sequence_length:
            candles = ohlc_candles[-sequence_length:]
        else:
            pad = [ohlc_candles[0]] * (sequence_length - len(ohlc_candles))
            candles = pad + ohlc_candles
            
        candles_feat = [{k: v for k, v in candle.items() if k in ['open', 'high', 'low', 'close']} for candle in candles]
        candles_np = np.array([[candle['open'], candle['high'], candle['low'], candle['close']] for candle in candles_feat])
        
        window_min = np.min(candles_np)
        window_max = np.max(candles_np)
        window_range = max(1e-9, window_max - window_min)
        
        candles_np = (candles_np - window_min) / window_range
        
        # Add positional encoding channel (matches training)
        pos = np.linspace(0, 1, sequence_length).reshape(-1, 1)
        candles_np = np.hstack([candles_np, pos]) # (100, 5)
        
        candles_np = np.expand_dims(candles_np, axis=0) # (1, 100, 5)
        
        with torch.no_grad():
            input_tensor = torch.tensor(candles_np, dtype=torch.float32)
            output = _nn_model(input_tensor)
            output = output.numpy()[0]
            print(f"DEBUG NN post-fix: raw_out={output}")
            
        start_idx_norm, end_idx_norm, price_high_norm, price_low_norm = output
        print(f"DEBUG NN: raw_out={output}, seq_len={sequence_length}")
        
        start_idx = max(0, min(int(round(start_idx_norm * sequence_length)), sequence_length - 1))
        end_idx = max(0, min(int(round(end_idx_norm * sequence_length)), sequence_length - 1))
        
        price_high = float((price_high_norm * window_range) + window_min)
        price_low = float((price_low_norm * window_range) + window_min)
        confidence = float(1 / (1 + abs(price_high - price_low)))
        confidence = max(0.0, min(1.0, confidence))
        time_start = candles[start_idx]['time']
        time_end = candles[end_idx]['time']
        return {
            'timeStart': time_start,
            'timeEnd': time_end,
            'priceHigh': price_high,
            'priceLow': price_low,
            'score': 1.0,
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