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
DB_PATH = os.path.join(ROOT_DIR, "Trading-Project", "data", "candles.db")

sys.path.append(BACKEND_DIR)
sys.path.append(ML2_DIR)

from feature_engine_v3 import build_features
from model_a import SegmentationModel, predict_heatmap

def test_usdjpy():
    device = torch.device('cpu')
    model = SegmentationModel().to(device)
    model_path = os.path.join(BACKEND_DIR, 'data', 'models', 'model_a.pt')
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Fetch a window of USDJPY where we expect consolidation (e.g. from heuristic)
    rows = conn.execute("SELECT open, high, low, close FROM candles WHERE symbol='USDJPY' AND timeframe='15m' LIMIT 500 OFFSET 1000").fetchall()
    conn.close()
    
    data = np.array([[r['open'], r['high'], r['low'], r['close']] for r in rows], dtype=np.float32)
    
    # Check a few windows
    found = False
    for i in range(0, 450, 10):
        window = data[i:i+50]
        if len(window) < 50: break
        
        features = build_features(window).to(device)
        heatmap = predict_heatmap(model, features.cpu().numpy())
        mx = heatmap.max()
        if mx > 0.15:
            print(f"Window {i}-{i+50}: Heatmap Max = {mx:.4f} (FIRE!)")
            found = True
        else:
            print(f"Window {i}-{i+50}: Heatmap Max = {mx:.4f}")

    if not found:
        print("No fires found in this 500-candle segment.")

if __name__ == "__main__":
    test_usdjpy()
