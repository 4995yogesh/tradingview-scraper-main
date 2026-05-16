import sys
import os
import torch
import numpy as np
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from feature_engine_v4 import build_features
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
        from model_a import load_model
        model_a = load_model(model_a_path)
        model_a.eval()
        print("ML2: Model A (Gated) loaded with safe loader")

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

def predict_v1(ohlc_candles: List[Dict], symbol: str = None, timeframe: str = None) -> Optional[Dict]:
    heatmap = []
    try:
        sequence_length = 100
        if not ohlc_candles:
            return {
                'heatmap': [],
                'confidence': 0,
                'model_version': 'v4-temporal-structure',
                'error': 'No candles available'
            }
            
        if isinstance(ohlc_candles, str):
            try:
                import json
                ohlc_candles = json.loads(ohlc_candles)
            except:
                pass
                
        # Convert all keys to lowercase to be robust
        ohlc_candles = [{k.lower(): v for k, v in c.items()} for c in ohlc_candles if isinstance(c, dict)]
        
        if len(ohlc_candles) >= sequence_length:
            ohlc_candles = ohlc_candles[-sequence_length:]
        else:
            # Pad beginning if not enough candles
            ohlc_candles = [ohlc_candles[0]] * (sequence_length - len(ohlc_candles)) + ohlc_candles

        from feature_builder import build_full_features
        features = build_full_features(ohlc_candles, symbol).cpu().numpy()
        
        initial_box = None
        refined_box = None
        quality = 0.05
        is_valid = False

        if model_a:
            heatmap_np = predict_heatmap(model_a, features)
            heatmap = heatmap_np.tolist()
            
            initial_box_dict = extract_box(heatmap_np, ohlc_candles, threshold=0.5) 
            if initial_box_dict:
                initial_box = np.array([
                    initial_box_dict['start_idx'], 
                    initial_box_dict['end_idx'], 
                    initial_box_dict['priceHigh'], 
                    initial_box_dict['priceLow']
                ], dtype=np.float32)

        if model_c and initial_box is not None:
            # Normalize to sequence_length
            input_box = np.array([initial_box[0]/float(sequence_length), initial_box[1]/float(sequence_length), 0.5, 0.5], dtype=np.float32)
            refined_box_vec = refine_predict(model_c, features, input_box)
            
            s_idx = int(np.clip(np.round(refined_box_vec[0] * sequence_length), 0, sequence_length - 1))
            e_idx = int(np.clip(np.round(refined_box_vec[1] * sequence_length), 0, sequence_length - 1))
            if s_idx > e_idx: s_idx, e_idx = e_idx, s_idx
            
            slice_c = ohlc_candles[s_idx:e_idx+1]
            if slice_c:
                p_high = max(c['high'] for c in slice_c)
                p_low  = min(c['low'] for c in slice_c)
                refined_box = [s_idx, e_idx, p_high, p_low]

        eval_box = refined_box if refined_box is not None else initial_box
        
        if model_d and eval_box is not None:
            input_box_d = np.array([eval_box[0]/float(sequence_length), eval_box[1]/float(sequence_length), 0.5, 0.5], dtype=np.float32)
            quality, is_valid = score_predict(model_d, features, input_box_d)

        # Map to final output
        final_box = eval_box
        
        res = {
            'heatmap': heatmap,
            'confidence': float(quality),
            'is_valid': bool(is_valid),
            'model_version': 'v4-temporal-structure',
        }
        
        if final_box is not None:
            idx1, idx2 = int(final_box[0]), int(final_box[1])
            res.update({
                'timeStart': ohlc_candles[idx1]['time'],
                'timeEnd': ohlc_candles[idx2]['time'],
                'priceHigh': float(final_box[2]),
                'priceLow': float(final_box[3]),
            })
        else:
            # Fallback to a small slice at the end if detection failed
            res.update({
                'timeStart': ohlc_candles[-5]['time'] if len(ohlc_candles) > 5 else ohlc_candles[0]['time'],
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
