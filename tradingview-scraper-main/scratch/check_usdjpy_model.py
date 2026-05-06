import sys
import os
import torch
import numpy as np
import sqlite3

# Setup paths
ROOT_DIR = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main"
BACKEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "backend")
ML2_DIR = os.path.join(BACKEND_DIR, "ml2")
DB_PATH = os.path.join(ROOT_DIR, "Trading-Project", "data", "candles.db")

sys.path.append(BACKEND_DIR)
sys.path.append(ML2_DIR)

from feature_engine_v2_1 import build_features
from model_a import SegmentationModel, predict_heatmap

def check_model_on_usdjpy():
    # Load model
    model = SegmentationModel()
    model_path = os.path.join(BACKEND_DIR, 'data', 'models', 'model_a.pt')
    model.load_state_dict(torch.load(model_path, map_location='cpu'))
    model.eval()
    
    # Load data
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM candles WHERE symbol='USDJPY' AND timeframe='15m' LIMIT 500").fetchall()
    conn.close()
    
    data = []
    for r in rows:
        # HACK: Shift USDJPY prices to EURUSD-like levels (in ATR units)
        # to see if the model fires on the pattern
        data.append([r['open'] - 47.0, r['high'] - 47.0, r['low'] - 47.0, r['close'] - 47.0])
    data = np.array(data, dtype=np.float32)
    
    print(f"Testing model on {len(data)} candles (SHIFTED USDJPY)...")
    
    # Check first 100 candles
    window = data[0:100]
    features = build_features(window).cpu().numpy()
    heatmap = predict_heatmap(model, features)
    
    print(f"Heatmap stats: Mean={heatmap.mean():.4f}, Max={heatmap.max():.4f}, Min={heatmap.min():.4f}")
    print(f"Top 5 values: {sorted(heatmap, reverse=True)[:5]}")

if __name__ == "__main__":
    check_model_on_usdjpy()
