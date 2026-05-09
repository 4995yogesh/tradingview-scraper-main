import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import torch

# Setup paths
ROOT_DIR = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main"
BACKEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "backend")
ML2_DIR = os.path.join(BACKEND_DIR, "ml2")

sys.path.append(ML2_DIR)
from feature_engine_v4 import build_features

def visualize_temporal_evolution(ohlc, asset_name="Asset"):
    """
    Plots the structural temporal features (v4) for a given window.
    """
    f = build_features(ohlc).cpu().numpy()
    
    # 22: ATR Slope (Volatility Decay)
    # 23: Compression Ratio (Range10 / Range30)
    # 24: Equilibrium Persistence (Time near median)
    # 26: Cumulative Rejection (Weighted touch density)
    # 30: Range Tightness (ATR / Range Width)
    
    fig, axes = plt.subplots(5, 1, figsize=(12, 15), sharex=True)
    
    # Price and Median
    axes[0].plot(ohlc[:, 3], color='black', alpha=0.5, label='Close')
    # Since features are centered on median, let's just plot the price
    axes[0].set_title(f"{asset_name} - Price Structure")
    axes[0].legend()
    
    # Volatility Decay (ATR Slope)
    axes[1].plot(f[:, 21], color='red', label='ATR Slope (Decay)')
    axes[1].axhline(0, color='gray', linestyle='--')
    axes[1].set_title("Volatility Trajectory")
    axes[1].legend()
    
    # Compression (Range Tightness & Ratio)
    axes[2].plot(f[:, 22], color='blue', label='Comp Ratio (R10/R30)')
    axes[2].plot(f[:, 29], color='cyan', label='Range Tightness (ATR/W)')
    axes[2].set_title("Compression Metrics")
    axes[2].legend()
    
    # Structural Rejection
    axes[3].plot(f[:, 25], color='purple', label='Rejection Accumulator')
    axes[3].set_title("Boundary Interaction Strength")
    axes[3].legend()
    
    # Equilibrium Persistence
    axes[4].plot(f[:, 23], color='green', label='Equilibrium Persistence')
    axes[4].set_title("Stability / Balance")
    axes[4].legend()
    
    plt.tight_layout()
    output_path = os.path.join(ROOT_DIR, "results", f"{asset_name.lower()}_temporal_evolution.png")
    plt.savefig(output_path)
    print(f"Visualization saved to {output_path}")

if __name__ == "__main__":
    # Generate random walk with simulated compression
    np.random.seed(42)
    n = 50
    # Start volatile
    walk = np.cumsum(np.random.randn(n) * 2.0) + 100
    # Dampen it over time
    for i in range(15, n):
        walk[i] = walk[i-1] + (np.random.randn() * (2.0 * (1 - (i-15)/35)))
    
    ohlc = np.zeros((n, 4))
    ohlc[:, 3] = walk
    ohlc[:, 0] = walk - np.random.randn(n) * 0.1
    ohlc[:, 1] = np.max(ohlc, axis=1) + 0.2
    ohlc[:, 2] = np.min(ohlc, axis=1) - 0.2
    
    visualize_temporal_evolution(ohlc, "Simulated_Compression")
