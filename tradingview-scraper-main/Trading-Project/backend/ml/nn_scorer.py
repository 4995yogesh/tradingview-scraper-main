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

from ml.shared_models import ConsolidationCNN

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
            heatmap_logits, prices_norm = _nn_model(input_tensor)
            
            # 1. Process Heatmap (Segmentation)
            heatmap = torch.sigmoid(heatmap_logits).numpy()[0] # (100,)
            print(f"DEBUG NN heatmap: max={heatmap.max():.4f}, mean={heatmap.mean():.4f}, thresholded={np.sum(heatmap > 0.5)}")
            
            # Find largest contiguous block > 0.5
            threshold = 0.5
            binary_mask = (heatmap > threshold).astype(np.int32)
            
            best_start, best_end = 0, 0
            current_start = -1
            max_len = 0
            
            for i in range(len(binary_mask)):
                if binary_mask[i] == 1:
                    if current_start == -1:
                        current_start = i
                else:
                    if current_start != -1:
                        length = i - current_start
                        if length > max_len:
                            max_len = length
                            best_start = current_start
                            best_end = i - 1
                        current_start = -1
            if current_start != -1: # check last block
                length = len(binary_mask) - current_start
                if length > max_len:
                    best_start = current_start
                    best_end = len(binary_mask) - 1
            
            # 2. Process Prices (Regression)
            prices = prices_norm.numpy()[0]
            y_high_norm, y_low_norm = prices[0], prices[1]
            
            # Inverse scaling
            price_high = float(y_high_norm * window_range + window_min)
            price_low  = float(y_low_norm * window_range + window_min)
            
            # Map indices back to timestamps
            time_start = candles[best_start]['time']
            time_end   = candles[best_end]['time']

            return {
                "timeStart": time_start,
                "timeEnd":   time_end,
                "priceHigh": price_high,
                "priceLow":  price_low,
                "score":     float(np.mean(heatmap[best_start : best_end+1]) if best_end > best_start else 0.0),
                "model_version": "nn_v2_segmentation"
            }

    except Exception as e:
        logging.error(f"Error in predict_box: {e}")
        return None
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