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
from model_a import SegmentationModel

def debug_inference():
    # Force CPU for stability during test
    device = torch.device('cpu')
    
    # Load model
    model = SegmentationModel().to(device)
    model_path = os.path.join(BACKEND_DIR, 'data', 'models', 'model_a.pt')
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    # Load EURUSD data (known good)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM candles WHERE symbol='EURUSD' AND timeframe='15m' LIMIT 500").fetchall()
    conn.close()
    
    data = np.array([[r['open'], r['high'], r['low'], r['close']] for r in rows], dtype=np.float32)
    
    # Test windows
    for i in range(0, 400, 50):
        window = data[i:i+50]
        # We need to monkeypatch build_features to use CPU or just ensure it does
        # build_features uses cuda if available. Let's check.
        features = build_features(window).to(device)
        
        with torch.no_grad():
            logits, _ = model(features.unsqueeze(0))
            probs = torch.sigmoid(logits).squeeze(0).cpu().numpy()
            
        print(f"Window {i}-{i+50}: Max Prob = {probs.max():.4f}")

if __name__ == "__main__":
    debug_inference()
