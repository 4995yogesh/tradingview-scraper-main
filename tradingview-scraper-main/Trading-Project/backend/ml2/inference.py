import sys
import os
import torch
import numpy as np
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from feature_engine_v2_1 import build_features
from model_a import SegmentationModel, predict_heatmap
from model_b import extract_box
from model_c import RefinementModel, refine_predict
from model_d import QualityScorer, score_predict

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
        print("ML2: Model A (Gated) loaded")

    model_c_path = os.path.join(backend_dir, 'data', 'models', 'model_c.pt')
    if os.path.exists(model_c_path):
        model_c = RefinementModel()
        model_c.load_state_dict(torch.load(model_c_path, map_location='cpu'))
        model_c.eval()
        print("ML2: Model C (Refinement) loaded")

    model_d_path = os.path.join(backend_dir, 'data', 'models', 'model_d.pt')
    if os.path.exists(model_d_path):
        model_d = QualityScorer()
        model_d.load_state_dict(torch.load(model_d_path, map_location='cpu'))
        model_d.eval()
        print("ML2: Model D (Dual Head) loaded")
except Exception as e:
    print(f"Error loading models: {e}")

def predict(ohlc_candles: List[Dict]) -> Optional[Dict]:
    heatmap = []
    try:
        if len(ohlc_candles) < 50:
            ohlc_candles = [ohlc_candles[0]] * (50 - len(ohlc_candles)) + ohlc_candles
        else:
            # We must pass the FULL context to build features to avoid alignment issues,
            # but model A is trained on the LAST 50. 
            # To stay consistent with training, we only look at the last 50.
            ohlc_candles = ohlc_candles[-50:]

        raw_ohlc = np.array([[c['open'], c['high'], c['low'], c['close']] for c in ohlc_candles], dtype=np.float32)
        features_tensor = build_features(raw_ohlc)
        features = features_tensor.cpu().numpy()
        
        initial_box = None
        refined_box = None
        quality = 0.05
        is_valid = False

        if model_a:
            heatmap_np = predict_heatmap(model_a, features)
            heatmap = heatmap_np.tolist()
            
            initial_box_dict = extract_box(heatmap_np, ohlc_candles, threshold=0.15) # Lower threshold for visual feedback
            if initial_box_dict:
                initial_box = np.array([
                    initial_box_dict['start_idx'], 
                    initial_box_dict['end_idx'], 
                    initial_box_dict['priceHigh'], 
                    initial_box_dict['priceLow']
                ], dtype=np.float32)

        if model_c and initial_box is not None:
            input_box = np.array([initial_box[0]/50.0, initial_box[1]/50.0, 0.5, 0.5], dtype=np.float32)
            refined_box_vec = refine_predict(model_c, features, input_box)
            
            s_idx = int(np.clip(np.round(refined_box_vec[0] * 50.0), 0, 49))
            e_idx = int(np.clip(np.round(refined_box_vec[1] * 50.0), 0, 49))
            if s_idx > e_idx: s_idx, e_idx = e_idx, s_idx
            
            # Robust price extraction
            slice_c = ohlc_candles[s_idx:e_idx+1]
            if slice_c:
                p_high = max(c['high'] for c in slice_c)
                p_low  = min(c['low'] for c in slice_c)
                refined_box = [s_idx, e_idx, p_high, p_low]

        if model_d and (refined_box or initial_box):
            eval_box = refined_box if refined_box else initial_box
            input_box_d = np.array([eval_box[0]/50.0, eval_box[1]/50.0, 0.5, 0.5], dtype=np.float32)
            quality, is_valid = score_predict(model_d, features, input_box_d)

        # Map to final output
        final_box = refined_box if refined_box else initial_box
        
        res = {
            'heatmap': heatmap,
            'confidence': float(quality) if is_valid else 0.01,
            'model_version': 'v2.1-stable-gated'
        }
        
        if final_box:
            idx1, idx2 = int(final_box[0]), int(final_box[1])
            res.update({
                'timeStart': ohlc_candles[idx1]['time'],
                'timeEnd': ohlc_candles[idx2]['time'],
                'priceHigh': float(final_box[2]),
                'priceLow': float(final_box[3]),
            })
        else:
            # Fallback empty box at end
            res.update({
                'timeStart': ohlc_candles[-2]['time'],
                'timeEnd': ohlc_candles[-1]['time'],
                'priceHigh': ohlc_candles[-1]['high'],
                'priceLow': ohlc_candles[-1]['low'],
            })
            
        return res

    except Exception as e:
        print(f"ML2 ERROR: Prediction failed: {e}")
        import traceback
        traceback.print_exc(file=sys.stdout)
        return {
            'heatmap': heatmap,
            'confidence': 0,
            'error': str(e)
        }