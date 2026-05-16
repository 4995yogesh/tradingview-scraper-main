import os
import sys
import json
import sqlite3
import numpy as np
import torch
from torch.utils.data import Dataset
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_builder import build_full_features

def to_unix(t):
    if isinstance(t, str):
        try:
            from datetime import datetime, timezone
            return datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
        except:
            return 0.0
    v = float(t)
    return v / 1000.0 if v > 2e12 else v

def get_htf_swings(symbol, htf_tf, start_ts, end_ts):
    import sqlite3
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(base_dir, 'data', 'candles.db')
    
    if not os.path.exists(db_path):
        return []
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    durations = {'60': 3600, '240': 14400, '1D': 86400, '1W': 604800}
    dur = durations.get(htf_tf, 3600)
    
    try:
        cursor.execute("""
            SELECT ts, open, high, low, close 
            FROM candles 
            WHERE symbol=? AND timeframe=? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (symbol, htf_tf, int(start_ts - 100 * dur), int(end_ts)))
        rows = cursor.fetchall()
    except Exception as e:
        print(f"DB Error: {e}")
        rows = []
    finally:
        conn.close()
        
    if len(rows) < 3:
        return []
        
    swings = []
    for i in range(1, len(rows) - 1):
        h = rows[i][2]
        l = rows[i][3]
        h_prev = rows[i-1][2]
        l_prev = rows[i-1][3]
        h_next = rows[i+1][2]
        l_next = rows[i+1][3]
        
        is_sh = h > h_prev and h > h_next
        is_sl = l < l_prev and l < l_next
        
        if is_sh:
            swings.append({'time': rows[i+1][0], 'price': h, 'type': 'high'})
        if is_sl:
            swings.append({'time': rows[i+1][0], 'price': l, 'type': 'low'})
            
    # Calculate mitigation times
    for s in swings:
        s['mitigated_at'] = float('inf')
        for row in rows:
            if row[0] > s['time']: # Strictly after confirmation
                if s['type'] == 'high' and row[2] >= s['price']:
                    s['mitigated_at'] = row[0]
                    break
                elif s['type'] == 'low' and row[3] <= s['price']:
                    s['mitigated_at'] = row[0]
                    break
            
    return swings

class ConsolidationDataset(Dataset):
    def __init__(self, db_path):
        self.db_path = db_path
        self.samples = []
        self._load()

    def _load(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Point 1 & 2: Include SKIPPED as negative samples
        cursor.execute("SELECT box_id, ohlc_context, user_box, time_start, time_end, status, symbol, timeframe FROM review_queue WHERE status IN ('LABELED','ANALYZED','SKIPPED') ORDER BY time_start ASC")
        rows = cursor.fetchall()
        conn.close()
        
        for row in rows:
            box_id, ohlc_context_str, user_box_str, db_time_start, db_time_end, status, symbol, timeframe = row
            candles = json.loads(ohlc_context_str)
            user_box_raw = json.loads(user_box_str) if user_box_str else None
            if isinstance(user_box_raw, list):
                user_box = user_box_raw[0] if user_box_raw else None
            else:
                user_box = user_box_raw
            
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import config

            if len(candles) >= config.SEQUENCE_LENGTH:
                candles = candles[-config.SEQUENCE_LENGTH:]
            else:
                # Pad beginning if not enough candles
                candles = [candles[0]] * (config.SEQUENCE_LENGTH - len(candles)) + candles
                
            # Check if features exist in DB
            feats = None
            try:
                conn2 = sqlite3.connect(self.db_path)
                cursor2 = conn2.cursor()
                cursor2.execute("SELECT feature_vec FROM nn_features WHERE box_id=?", (box_id,))
                row2 = cursor2.fetchone()
                if row2:
                    feats = np.array(json.loads(row2[0]))
                conn2.close()
            except Exception as e:
                print(f"Error reading from nn_features: {e}")

            if feats is None:
                feats = build_full_features(candles, symbol).cpu().numpy()
                # Save to DB for future loads
                try:
                    conn3 = sqlite3.connect(self.db_path)
                    cursor3 = conn3.cursor()
                    cursor3.execute(
                        "INSERT OR IGNORE INTO nn_features (box_id, feature_vec) VALUES (?, ?)",
                        (box_id, json.dumps(feats.tolist()))
                    )
                    conn3.commit()
                    conn3.close()
                except Exception as e:
                    print(f"Failed to cache features for {box_id}: {e}")

            
            if len(feats) >= 100:
                feats = feats[-100:]
            else:
                pad = np.zeros((100-len(feats), feats.shape[1]))
                feats = np.vstack([pad, feats])
            
            if len(candles) >= 100:
                candles_50 = candles[-100:]
            else:
                candles_50 = [candles[0]]*(100-len(candles)) + candles
            
            seg_mask = np.zeros(100, dtype=np.float32)
            
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
            si = max(0, min(si, 99))
            ei = max(0, min(ei, 99))
            
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
                'is_consolidation': is_consolidation,
                'box_id': box_id
            })

    def get_sampler(self):
        from torch.utils.data import WeightedRandomSampler
        import os
        import json
        
        labels = [s['is_consolidation'] for s in self.samples]
        neg_count = labels.count(0)
        pos_count = labels.count(1)
        
        # If one class is missing, fallback to uniform
        if neg_count == 0 or pos_count == 0:
            return None
            
        neg_weight = 1.0 / neg_count
        pos_weight = 1.0 / pos_count
        
        # Load hard samples
        hard_ids = set()
        try:
            # ml2 is inside backend, data/models is inside backend
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            hard_samples_path = os.path.join(base_dir, 'data', 'models', 'hard_samples.json')
            if os.path.exists(hard_samples_path):
                with open(hard_samples_path, 'r') as f:
                    hard_samples = json.load(f)
                    hard_ids = set(s['box_id'] for s in hard_samples)
                    print(f"Loaded {len(hard_ids)} hard samples for priority weighting")
        except Exception as e:
            print(f"Error loading hard samples for weighting: {e}")
            
        weights = []
        for s in self.samples:
            w = pos_weight if s['is_consolidation'] == 1 else neg_weight
            if s.get('box_id') in hard_ids:
                w *= 3.0 # Give 3x priority to hard samples
                
            weights.append(w)
            
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
            'is_consolidation': torch.LongTensor([s['is_consolidation']]),
            'box_id': s.get('box_id', 'N/A')
        }