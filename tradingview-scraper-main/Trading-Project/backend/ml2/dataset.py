import os
import sys
import json
import sqlite3
import numpy as np
import torch
from torch.utils.data import Dataset
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_engine_v2_1 import build_features

def to_unix(t):
    if isinstance(t, str):
        try:
            from datetime import datetime, timezone
            return datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
        except:
            return 0.0
    v = float(t)
    return v / 1000.0 if v > 2e12 else v

class ConsolidationDataset(Dataset):
    def __init__(self, db_path):
        self.db_path = db_path
        self.samples = []
        self._load()

    def _load(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Point 1 & 2: Include SKIPPED as negative samples
        cursor.execute("SELECT box_id, ohlc_context, user_box, time_start, time_end, status FROM review_queue WHERE status IN ('LABELED','ANALYZED','SKIPPED')")
        rows = cursor.fetchall()
        conn.close()
        
        for row in rows:
            box_id, ohlc_context_str, user_box_str, db_time_start, db_time_end, status = row
            candles = json.loads(ohlc_context_str)
            user_box_raw = json.loads(user_box_str) if user_box_str else None
            if isinstance(user_box_raw, list):
                user_box = user_box_raw[0] if user_box_raw else None
            else:
                user_box = user_box_raw
            
            if len(candles) < 5:
                continue
            
            feats = build_features(np.array([[c['open'], c['high'], c['low'], c['close']] for c in candles])).cpu().numpy()
            
            if len(feats) >= 50:
                feats = feats[-50:]
            else:
                pad = np.zeros((50-len(feats), 21))
                feats = np.vstack([pad, feats])
            
            if len(candles) >= 50:
                candles_50 = candles[-50:]
            else:
                candles_50 = [candles[0]]*(50-len(candles)) + candles
            
            seg_mask = np.zeros(50, dtype=np.float32)
            
            b_start = to_unix(db_time_start)
            b_end = to_unix(db_time_end)
            if user_box:
                if 'timeStart' in user_box:
                    b_start = to_unix(user_box['timeStart'])
                if 'timeEnd' in user_box:
                    b_end = to_unix(user_box['timeEnd'])
            
            ts_list = [to_unix(c['time']) for c in candles_50]
            si = int(np.argmin([abs(t - b_start) for t in ts_list]))
            ei = int(np.argmin([abs(t - b_end) for t in ts_list]))
            si, ei = min(si,ei), max(si,ei)
            
            # Point 5: Soft Segmentation Labels with Clamped Indices
            si = max(0, min(si, 49))
            ei = max(0, min(ei, 49))
            
            if status != 'SKIPPED':
                # Core [si+2 : ei-2] = 1.0 (if window allows)
                core_si = min(si + 2, 49)
                core_ei = max(ei - 2, 0)
                if core_si <= core_ei:
                    seg_mask[core_si : core_ei+1] = 1.0
                
                # Edges [si, si+1, ei-1, ei] = 0.7
                for idx in [si, si+1, ei-1, ei]:
                    if 0 <= idx <= 49:
                        seg_mask[idx] = max(seg_mask[idx], 0.7)
                
                # Transition [si-1, ei+1] = 0.3
                for idx in [si-1, ei+1]:
                    if 0 <= idx <= 49:
                        seg_mask[idx] = max(seg_mask[idx], 0.3)
            else:
                # SKIPPED is all 0.0 for seg_mask
                seg_mask[:] = 0.0
            
            all_highs = feats[:, 1]
            all_lows = feats[:, 2]
            h_range = all_highs.max() - all_highs.min() or 1e-9
            l_range = all_lows.max() - all_lows.min() or 1e-9
            
            if user_box:
                high_norm = (float(user_box['priceHigh']) - all_highs.min()) / h_range
                low_norm = (float(user_box['priceLow']) - all_lows.min()) / l_range
            else:
                high_norm, low_norm = 0.5, 0.5
            
            high_norm = float(np.clip(high_norm, 0.0, 2.0))
            low_norm = float(np.clip(low_norm, 0.0, 2.0))
            
            # Point 1: Quality Score & Consolidation Flag
            if status == 'SKIPPED':
                quality_score = 0.0
                is_consolidation = 0
            elif user_box is not None:
                quality_score = 1.0
                is_consolidation = 1
            else:
                quality_score = 0.6
                is_consolidation = 1
            
            # Point 8: Mild Augmentation (Price jitter ±1-2%, Time shift ±1-2 candles)
            if np.random.rand() < 0.3: # 30% chance to augment
                jitter = 1.0 + (np.random.rand() - 0.5) * 0.04 # ±2%
                feats[:, 0:4] *= jitter # O, H, L, C
            
            self.samples.append({
                'features': feats.astype(np.float32),
                'seg_mask': seg_mask,
                'box_coords': [float(si)/50.0, float(ei)/50.0, high_norm, low_norm],
                'quality_score': quality_score,
                'is_consolidation': is_consolidation
            })

    def get_sampler(self):
        from torch.utils.data import WeightedRandomSampler
        labels = [s['is_consolidation'] for s in self.samples]
        neg_count = labels.count(0)
        pos_count = labels.count(1)
        
        # If one class is missing, fallback to uniform
        if neg_count == 0 or pos_count == 0:
            return None
            
        neg_weight = 1.0 / neg_count
        pos_weight = 1.0 / pos_count
        weights = [pos_weight if l == 1 else neg_weight for l in labels]
        return WeightedRandomSampler(weights, len(weights))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        s = self.samples[idx]
        return {
            'features': torch.FloatTensor(s['features']),
            'seg_mask': torch.FloatTensor(s['seg_mask']),
            'box_coords': torch.FloatTensor(s['box_coords']),
            'quality_score': torch.FloatTensor([s['quality_score']]),
            'is_consolidation': torch.LongTensor([s['is_consolidation']])
        }