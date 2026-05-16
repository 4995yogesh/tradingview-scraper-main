import os
import sys
import numpy as np
import torch
from datetime import datetime, timedelta

# Add parent dir to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

from feature_engine_v4 import build_features

def to_unix(t):
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
        except:
            return 0.0
    v = float(t)
    return v / 1000.0 if v > 2e12 else v

def get_htf_swings(symbol, htf_tf, start_ts, end_ts):
    import sqlite3
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

def build_full_features(candles, symbol):
    """
    Centralized Feature Builder.
    Generates 43 features for a sequence of candles.
    
    Args:
        candles: List of dicts containing 'open', 'high', 'low', 'close', 'volume', 'time'
        symbol: String symbol name (for HTF swings)
        
    Returns:
        torch.Tensor of shape [SeqLen, 43]
    """
    n = len(candles)
    assert n == config.SEQUENCE_LENGTH, f"Expected {config.SEQUENCE_LENGTH} candles, got {n}"
    
    # 1. Get 32 features from feature_engine_v4
    ohlc_np = np.array([[float(c['open']), float(c['high']), float(c['low']), float(c['close'])] for c in candles])
    v4_features = build_features(ohlc_np) # Returns [SeqLen, 32]
    
    # 2. Extract volume and time features (3 features)
    volumes = []
    hours = []
    days = []
    
    for c in candles:
        volumes.append(float(c.get('volume', 0.0)))
        try:
            dt_utc = datetime.fromisoformat(c['time'].replace('Z', '+00:00'))
            dt_ist = dt_utc + timedelta(hours=5, minutes=30)
            hours.append((dt_ist.hour * 60 + dt_ist.minute) / 1440.0)
            days.append(dt_ist.weekday() / 6.0)
        except:
            hours.append(0.5)
            days.append(0.5)
            
    # Normalize volume relative to this window
    max_v = max(volumes) or 1.0
    volumes_norm = [v / max_v for v in volumes]
    
    # 3. Fetch and map HTF swings (8 features)
    htf_tfs = ['60', '240', '1D', '1W']
    candle_ts = [to_unix(c['time']) for c in candles]
    min_ts = min(candle_ts)
    max_ts = max(candle_ts)
    
    htf_features = []
    for htf in htf_tfs:
        swings = get_htf_swings(symbol, htf, min_ts, max_ts)
        
        htf_sh = []
        htf_sl = []
        for i, t in enumerate(candle_ts):
            t_close = float(candles[i]['close'])
            avail = [s for s in swings if s['time'] <= t and t < s.get('mitigated_at', float('inf'))]
            
            # Most recent swing high
            sh_avail = [s for s in avail if s['type'] == 'high']
            if sh_avail:
                last_sh = max(sh_avail, key=lambda x: x['time'])
                htf_sh.append(last_sh['price'])
            else:
                htf_sh.append(t_close)
                
            # Most recent swing low
            sl_avail = [s for s in avail if s['type'] == 'low']
            if sl_avail:
                last_sl = max(sl_avail, key=lambda x: x['time'])
                htf_sl.append(last_sl['price'])
            else:
                htf_sl.append(t_close)
                
        htf_features.extend([htf_sh, htf_sl])
        
    # Combine all features
    extra_feats_np = np.column_stack([volumes_norm, hours, days] + htf_features)
    extra_feats_torch = torch.from_numpy(extra_feats_np).float().to(v4_features.device)
    
    full_features = torch.cat([v4_features, extra_feats_torch], dim=1)
    
    assert full_features.shape[1] == config.FEATURE_COUNT, f"Expected {config.FEATURE_COUNT} features, got {full_features.shape[1]}"
    
    return full_features
