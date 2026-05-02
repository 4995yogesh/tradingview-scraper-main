import sys
import os
import torch
import numpy as np
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from features import compute_features, normalize_features
from model_a import SegmentationModel
from model_b import extract_box
from model_c import RefinementModel
from model_d import QualityScorer

model_a = None
model_c = None
model_d = None

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    model_a_path = os.path.join(backend_dir, 'data', 'models', 'model_a.pt')
    if os.path.exists(model_a_path):
        model_a = SegmentationModel()
        model_a.load_state_dict(torch.load(model_a_path, map_location='cpu'))
        model_a.eval()
        print("ML2: Model A loaded")

    model_c_path = os.path.join(backend_dir, 'data', 'models', 'model_c.pt')
    if os.path.exists(model_c_path):
        model_c = RefinementModel()
        model_c.load_state_dict(torch.load(model_c_path, map_location='cpu'))
        model_c.eval()
        print("ML2: Model C loaded")

    model_d_path = os.path.join(backend_dir, 'data', 'models', 'model_d.pt')
    if os.path.exists(model_d_path):
        model_d = QualityScorer()
        model_d.load_state_dict(torch.load(model_d_path, map_location='cpu'))
        model_d.eval()
        print("ML2: Model D loaded")
except Exception as e:
    print(f"Error loading models: {e}")

def predict(ohlc_candles: List[Dict]) -> Optional[Dict]:
    try:
        if len(ohlc_candles) < 50:
            ohlc_candles = [ohlc_candles[0]] * (50 - len(ohlc_candles)) + ohlc_candles
        else:
            ohlc_candles = ohlc_candles[-50:]

        features = normalize_features(compute_features(ohlc_candles))
        heatmap = None
        initial_box = None
        refined_box = None
        quality = 0.5

        if model_a:
            from model_a import predict_heatmap
            heatmap = predict_heatmap(model_a, features)

        if heatmap is not None:
            initial_box_dict = extract_box(heatmap, ohlc_candles)
            if initial_box_dict:
                initial_box = np.array([
                    initial_box_dict['start_idx'], 
                    initial_box_dict['end_idx'], 
                    initial_box_dict['priceHigh'], 
                    initial_box_dict['priceLow']
                ], dtype=np.float32)

        if model_c and initial_box is not None:
            from model_c import refine
            refined_box_vec = refine(model_c, features, initial_box)
            # De-normalize indices (Model C was trained on 0-1)
            s_idx = int(np.clip(np.round(refined_box_vec[0] * 50.0), 0, 49))
            e_idx = int(np.clip(np.round(refined_box_vec[1] * 50.0), 0, 49))
            print(f"ML2 Debug: Model C output {refined_box_vec[:2]}, Scaled Indices: {s_idx}, {e_idx}")
            if s_idx > e_idx: s_idx, e_idx = e_idx, s_idx
            
            # Since training normalization for prices was buggy in dataset.py, 
            # we re-calculate high/low from candles using the refined indices
            # to avoid huge boxes.
            p_high = max(c['high'] for c in ohlc_candles[s_idx:e_idx+1])
            p_low  = min(c['low'] for c in ohlc_candles[s_idx:e_idx+1])
            
            refined_box = [s_idx, e_idx, p_high, p_low]
            
            # Smart Fallback: If Model C predicts nearly the whole window (>= 45 candles),
            # it's likely under-trained for this context. Fallback to Initial Box (Model B).
            if (e_idx - s_idx) >= 45:
                refined_box = [
                    initial_box_dict['start_idx'], 
                    initial_box_dict['end_idx'], 
                    initial_box_dict['priceHigh'], 
                    initial_box_dict['priceLow']
                ]
                print(f"ML2: Refinement too wide ({e_idx - s_idx}c), falling back to Model B extraction.")

        if model_d and refined_box is not None:
            from model_d import score
            # model_d expects [start, end, high, low] - we pass the indices + prices
            quality = score(model_d, features, np.array(refined_box, dtype=np.float32))

        if refined_box is not None:
            idx1, idx2 = refined_box[0], refined_box[1]
            timeStart = ohlc_candles[idx1]['time']
            timeEnd = ohlc_candles[idx2]['time']
            priceHigh = float(refined_box[2])
            priceLow = float(refined_box[3])
        elif initial_box is not None:
            # Fallback to Model B (extract_box) output
            timeStart = initial_box_dict['timeStart']
            timeEnd = initial_box_dict['timeEnd']
            priceHigh = initial_box_dict['priceHigh']
            priceLow = initial_box_dict['priceLow']
        else:
            timeStart = ohlc_candles[0]['time']
            timeEnd = ohlc_candles[-1]['time']
            priceHigh = max(candle['high'] for candle in ohlc_candles)
            priceLow = min(candle['low'] for candle in ohlc_candles)

        return {
            'timeStart': timeStart,
            'timeEnd': timeEnd,
            'priceHigh': priceHigh,
            'priceLow': priceLow,
            'confidence': float(quality),
            'heatmap': heatmap.tolist() if heatmap is not None else [],
            'model_version': 'v2.1-stable'
        }
    except Exception as e:
        print(f"Error during prediction: {e}")
        return None