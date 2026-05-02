import sys
import os
import json
import sqlite3
import numpy as np
import torch
import matplotlib.pyplot as plt

# Ensure local imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from features import compute_features, normalize_features
from model_a import SegmentationModel, predict_heatmap

def visualize_sample(db_path, model_path, output_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT ohlc_context, user_box FROM review_queue WHERE status = 'LABELED' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        print("No labeled samples found in DB.")
        return

    ohlc_context = json.loads(row[0])
    
    # Pre-process features
    feats = compute_features(ohlc_context)
    feats = normalize_features(feats)
    
    if len(feats) >= 50:
        feats = feats[-50:]
        ohlc_50 = ohlc_context[-50:]
    else:
        pad = np.zeros((50 - len(feats), 12))
        feats = np.vstack([pad, feats])
        ohlc_50 = [ohlc_context[0]] * (50 - len(ohlc_context)) + ohlc_context

    # Load model
    model = SegmentationModel()
    model.load_state_dict(torch.load(model_path, map_location='cpu'))
    model.eval()

    # Predict heatmap
    heatmap = predict_heatmap(model, feats)

    # Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
    
    # Plot Candles (simple)
    closes = [c['close'] for c in ohlc_50]
    ax1.plot(closes, color='blue', alpha=0.6)
    ax1.set_title("Price Context (Last 50 Candles)")
    
    # Plot Heatmap
    im = ax2.imshow(heatmap.reshape(1, -1), aspect='auto', cmap='hot', vmin=0, vmax=1)
    ax2.set_title("Model A Heatmap (Consolidation Probability)")
    ax2.set_yticks([])
    fig.colorbar(im, ax=ax2, orientation='horizontal')

    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Heatmap visualization saved to: {output_path}")

if __name__ == "__main__":
    backend_dir = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend"
    db_path = os.path.join(backend_dir, "training_set.db")
    model_path = os.path.join(backend_dir, "data", "models", "model_a.pt")
    output_path = os.path.join(backend_dir, "scratch", "model_a_heatmap.png")
    
    visualize_sample(db_path, model_path, output_path)
