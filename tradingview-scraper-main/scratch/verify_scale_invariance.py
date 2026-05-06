import sys
import os
import torch
import numpy as np
import sqlite3
import matplotlib.pyplot as plt

# Setup paths
ROOT_DIR = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main"
BACKEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "backend")
ML2_DIR = os.path.join(BACKEND_DIR, "ml2")
CANDLE_DB = os.path.join(ROOT_DIR, "Trading-Project", "data", "candles.db")

sys.path.append(BACKEND_DIR)
sys.path.append(ML2_DIR)

from feature_engine_v3 import build_features

def get_data(symbol, count=1000):
    conn = sqlite3.connect(CANDLE_DB)
    conn.row_factory = sqlite3.Row
    query = f"SELECT open, high, low, close FROM candles WHERE symbol='{symbol}' AND timeframe='15m' LIMIT {count}"
    rows = conn.execute(query).fetchall()
    conn.close()
    return np.array([[r['open'], r['high'], r['low'], r['close']] for r in rows], dtype=np.float32)

def verify():
    print("--- SCALE INVARIANCE VERIFICATION (v3) ---")
    eur = get_data("EURUSD", 1000)
    jpy = get_data("USDJPY", 1000)
    
    if len(eur) < 50 or len(jpy) < 50:
        print("Error: Insufficient data for comparison.")
        return

    # Extract features for a window
    f_eur = build_features(eur[:50]).cpu().numpy()
    f_jpy = build_features(jpy[:50]).cpu().numpy()
    
    channels = [
        "O_Rel", "H_Rel", "L_Rel", "C_Rel", 
        "Body", "Range", "U_Wick", "L_Wick", "Dir",
        "VolRat", "Mom3", "Slope",
        "RH_Rel", "RL_Rel", "R_Width", "R_Stab",
        "Overlap", "Prox", "Impulse", "Density", "Fake"
    ]
    
    print(f"{'Channel':<10} | {'EUR Mean':<10} | {'JPY Mean':<10} | {'Ratio':<10}")
    print("-" * 50)
    
    for i in range(21):
        m1 = np.mean(np.abs(f_eur[:, i]))
        m2 = np.mean(np.abs(f_jpy[:, i]))
        ratio = m2 / (m1 + 1e-8)
        print(f"{channels[i]:<10} | {m1:<10.4f} | {m2:<10.4f} | {ratio:<10.2f}")

    # Plot Comparison for first 4 channels (Rel OHLC)
    plt.figure(figsize=(12, 6))
    for i in range(4):
        plt.subplot(2, 2, i+1)
        plt.plot(f_eur[:, i], label='EURUSD', color='blue', alpha=0.7)
        plt.plot(f_jpy[:, i], label='USDJPY', color='orange', alpha=0.7)
        plt.title(f"Channel {i+1}: {channels[i]}")
        plt.legend()
    
    plt.tight_layout()
    os.makedirs("results", exist_ok=True)
    plt.savefig("results/feature_comparison_v3.png")
    print("\nPlot saved to results/feature_comparison_v3.png")

if __name__ == "__main__":
    verify()
