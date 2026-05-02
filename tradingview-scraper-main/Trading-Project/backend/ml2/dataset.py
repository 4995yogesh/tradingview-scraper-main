import os
import sys
import json
import sqlite3
import numpy as np
import torch
from torch.utils.data import Dataset
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import compute_features, normalize_features

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
        self._add_negatives()

    def _load(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT box_id, ohlc_context, user_box, time_start, time_end FROM review_queue WHERE status IN ('LABELED','ANALYZED')")
        rows = cursor.fetchall()
        conn.close()
        
        for row in rows:
            box_id, ohlc_context_str, user_box_str, db_time_start, db_time_end = row
            candles = json.loads(ohlc_context_str)
            user_box_raw = json.loads(user_box_str) if user_box_str else None
            if isinstance(user_box_raw, list):
                user_box = user_box_raw[0] if user_box_raw else None
            else:
                user_box = user_box_raw
            
            if len(candles) < 5:
                continue
            
            feats = compute_features(candles)
            feats = normalize_features(feats)
            
            if len(feats) >= 50:
                feats = feats[-50:]
            else:
                pad = np.zeros((50-len(feats), 12))
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
            seg_mask[si:ei+1] = 1.0
            
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
            
            quality_score = 1.0 if user_box is not None else 0.6
            
            self.samples.append({
                'features': feats.astype(np.float32),
                'seg_mask': seg_mask,
                'box_coords': [float(si)/50.0, float(ei)/50.0, high_norm, low_norm],
                'quality_score': quality_score,
                'is_consolidation': 1
            })

    def _add_negatives(self):
        for s in self.samples.copy():
            neg = {
                'features': s['features'],
                'seg_mask': np.zeros(50, dtype=np.float32),
                'box_coords': [0.0, 0.0, 0.0, 0.0],
                'quality_score': 0.0,
                'is_consolidation': 0
            }
            self.samples.append(neg)

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