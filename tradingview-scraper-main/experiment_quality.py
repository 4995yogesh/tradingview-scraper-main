import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.join(os.getcwd(), "Trading-Project"))
sys.path.append(os.path.join(os.getcwd(), "Trading-Project", "backend"))

from ml.quality.data import build_quality_dataset
from ml.quality.trainer import train_quality_model

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("=== Starting Quality Model Experiment ===")
    
    print("\n1. Building Dataset (Scraping labels and extracting new features)...")
    build_quality_dataset()
    
    print("\n2. Training Regression Model...")
    train_quality_model()
    
    print("\n=== Experiment Complete ===")
