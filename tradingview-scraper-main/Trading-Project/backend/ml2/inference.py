import sys
import os
import threading
import torch
import numpy as np
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from feature_engine_v4 import build_features
from model_a import SegmentationModel, predict_heatmap
from model_b import extract_box
from model_c import RefinementModel, refine_predict
from model_d import QualityScorer, score_predict
from timesfm_predictor import TimesFMPredictor

# Pattern Memory System (Phase 4–5)
try:
    _pm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pattern_memory")
    sys.path.insert(0, _pm_dir)
    from pattern_db import PatternMemoryDB
    from similarity_engine import PatternSimilarityEngine
    from outcome_intelligence import OutcomeIntelligence
    _pattern_db     = PatternMemoryDB()
    _pattern_engine = PatternSimilarityEngine()
    _outcome_intel  = OutcomeIntelligence()
    _PM_AVAILABLE   = True
except Exception as _pm_err:
    print(f"ML2: Pattern Memory unavailable: {_pm_err}")
    _pattern_db = _pattern_engine = _outcome_intel = None
    _PM_AVAILABLE = False


def _init_pattern_index():
    """Load or build FAISS index in a background thread."""
    if not _PM_AVAILABLE:
        return
    try:
        loaded = _pattern_engine.load_index()
        if not loaded:
            print("ML2: Pattern index not found on disk — building now...")
            n = _pattern_engine.build_index(_pattern_db)
            print(f"ML2: Pattern FAISS index built: {n} vectors")
        else:
            print(f"ML2: Pattern FAISS index loaded: {_pattern_engine.size} vectors")
    except Exception as e:
        print(f"ML2: Pattern index init failed: {e}")


threading.Thread(target=_init_pattern_index, daemon=True, name="PatternIndexInit").start()


model_a = None
model_c = None
model_d = None
timesfm_predictor = None


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

# Initialize TimesFM predictor separately — optional, has heavy JAX deps
try:
    timesfm_predictor = TimesFMPredictor(context_len=512, horizon_len=50)
except Exception as e:
    print(f"ML2: TimesFM predictor unavailable (optional): {e}")
    timesfm_predictor = None

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
        
        # Keep original candles (up to 512) for TimesFM — before 100-candle truncation
        original_candles = ohlc_candles[-512:] if len(ohlc_candles) > 512 else list(ohlc_candles)

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

        # --- TimesFM Breakout Forecast ---
        breakout_forecast = None
        if timesfm_predictor and final_box is not None:
            try:
                forecast = timesfm_predictor.forecast_close_prices(original_candles)
                price_high = float(final_box[2])
                price_low  = float(final_box[3])
                breakout_up   = bool(np.any(forecast > price_high))
                breakout_down = bool(np.any(forecast < price_low))
                direction = 'UP' if breakout_up else ('DOWN' if breakout_down else 'NONE')
                breakout_forecast = {
                    'breakout_risk': 'HIGH' if (breakout_up or breakout_down) else 'LOW',
                    'breakout_direction': direction,
                    'forecast_horizon': int(timesfm_predictor.horizon_len),
                    'forecast_min': float(np.min(forecast)),
                    'forecast_max': float(np.max(forecast)),
                    'forecast_last': float(forecast[-1]),
                }
            except Exception as tfm_e:
                print(f"ML2: TimesFM forecast failed: {tfm_e}")
                breakout_forecast = {'error': str(tfm_e)}

        # --- Pattern Memory Intelligence (Phase 4-5) ---
        pattern_intelligence = None
        if _PM_AVAILABLE and timesfm_predictor and _pattern_engine.size > 0:
            try:
                embedding = timesfm_predictor.get_embedding(original_candles)
                top_k_results = _pattern_engine.search(embedding, k=50)
                if top_k_results:
                    pids   = [pid for pid, _ in top_k_results]
                    scores = [score for _, score in top_k_results]
                    matches = _pattern_db.get_patterns_by_ids(pids)
                    intelligence = _outcome_intel.compute(matches, scores, horizon=20)
                    pattern_intelligence = intelligence.to_dict()
            except Exception as pm_e:
                print(f"ML2: Pattern intelligence failed: {pm_e}")
                pattern_intelligence = {'error': str(pm_e)}

        res = {
            'heatmap': heatmap,
            'confidence': float(quality),
            'is_valid': bool(is_valid),
            'model_version': 'v4-temporal-structure',
        }
        if breakout_forecast is not None:
            res['breakout_forecast'] = breakout_forecast
        if pattern_intelligence is not None:
            res['pattern_intelligence'] = pattern_intelligence
        
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
