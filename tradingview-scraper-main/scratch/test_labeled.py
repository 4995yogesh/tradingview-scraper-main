import sys
import os
import torch
import numpy as np
import sqlite3
import json

# Setup paths
ROOT_DIR = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main"
BACKEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "backend")
ML2_DIR = os.path.join(BACKEND_DIR, "ml2")

sys.path.append(BACKEND_DIR)
sys.path.append(ML2_DIR)

from feature_engine_v2_1 import build_features
from model_a import SegmentationModel, predict_heatmap

def test_labeled():
    device = torch.device('cpu')
    model = SegmentationModel().to(device)
    model_path = os.path.join(BACKEND_DIR, 'data', 'models', 'model_a.pt')
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    conn = sqlite3.connect(os.path.join(BACKEND_DIR, 'training_set.db'))
    row = conn.execute("SELECT ohlc_context, symbol, status FROM review_queue WHERE status='LABELED' LIMIT 1").fetchone()
    conn.close()
    
    if not row:
        print("No LABELED boxes found.")
        return
        
    candles = json.loads(row[0])
    symbol = row[1]
    print(f"Testing on {symbol} box (status: {row[2]}) with {len(candles)} candles.")
    
    ohlc = np.array([[c['open'], c['high'], c['low'], c['close']] for c in candles], dtype=np.float32)
    # Ensure 50 length
    if len(ohlc) >= 50:
        ohlc = ohlc[-50:]
    else:
        pad = np.tile(ohlc[0], (50 - len(ohlc), 1))
        ohlc = np.vstack([pad, ohlc])
        
    features = build_features(ohlc).to(device)
    heatmap = predict_heatmap(model, features.cpu().numpy())
    
    print(f"Heatmap Max: {heatmap.max():.4f}")
    print(f"Top 5: {sorted(heatmap, reverse=True)[:5]}")

if __name__ == "__main__":
    test_labeled()
