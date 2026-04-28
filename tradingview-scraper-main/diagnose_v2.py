import sqlite3
import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
import sys

# Add project root to path
sys.path.append(os.path.join(os.getcwd(), "Trading-Project"))
sys.path.append(os.path.join(os.getcwd(), "Trading-Project", "backend"))

from ml.quality.db import DB_PATH as QUALITY_DB_PATH, get_all_samples as get_quality_samples
from ml.quality.features import FEATURE_NAMES, extract_quality_features
from ml import db as ml_db
from pipeline.data.db import candle_db

def run_diagnosis():
    # 1. Dataset change check
    labels = ml_db.get_all_labels()
    print(f"total_samples_collected: {len(labels)}")
    
    # Check for relabelled boxes
    from collections import Counter
    box_counts = Counter([l['box_id'] for l in labels])
    relabelled = [bid for bid, count in box_counts.items() if count > 1]
    print(f"number_of_modified_labels (relabelled): {len(relabelled)}")
    
    # Show examples of relabelled boxes (before and after)
    print("\n--- Relabelled Examples (Before vs After) ---")
    for bid in relabelled[:5]:
        history = [l for l in labels if l['box_id'] == bid]
        history.sort(key=lambda x: x['created_at'])
        print(f"\nBox ID: {bid}")
        for i, entry in enumerate(history):
            status = "BEFORE" if i == 0 else f"AFTER {i}"
            print(f"  {status}: Label={entry['label']}, Created={entry['created_at']}")
            # Mock feature extraction to show change (if any)
            # Actually feature extraction is deterministic based on box and candles
            # so unless the coordinates changed (unlikely for FP/FN fix), features stay same.
    
    quality_samples = get_quality_samples()
    df = pd.DataFrame([json.loads(s['features']) for s in quality_samples], columns=FEATURE_NAMES)
    df['label_score'] = [s['label_score'] for s in quality_samples]
    df['box_id'] = [s['box_id'] for s in quality_samples]
    
    print("\n--- Feature Stats (Normalization Check) ---")
    stats = df[FEATURE_NAMES].describe().loc[['min', 'max', 'mean']]
    print(stats.to_string())

    import lightgbm as lgb
    X = df[FEATURE_NAMES].values
    y = df['label_score'].values
    model_path = os.path.join(os.path.dirname(QUALITY_DB_PATH), "quality_models", "quality_lgb_v1.txt")
    if os.path.exists(model_path):
        model = lgb.Booster(model_file=model_path)
        preds = model.predict(X)
        df['pred'] = preds
        
        # FP: Pred >= 0.75, Actual < 0.5
        fps = df[(df['pred'] >= 0.75) & (df['label_score'] < 0.5)]
        print(f"\nTotal FPs found: {len(fps)}")
        for _, fp_row in fps.head(3).iterrows():
            print(f"\nFP {fp_row['box_id']}: Pred={fp_row['pred']:.4f}, Actual={fp_row['label_score']:.4f}")
            # Find nearest GOOD
            good_pool = df[df['label_score'] >= 0.75]
            vec = fp_row[FEATURE_NAMES].values.astype(float)
            dists = np.linalg.norm(good_pool[FEATURE_NAMES].values - vec, axis=1)
            min_idx = np.argmin(dists)
            nearest_good = good_pool.iloc[min_idx]
            print(f"  Nearest GOOD ({nearest_good['box_id']}): Dist={dists[min_idx]:.6f}")

if __name__ == "__main__":
    run_diagnosis()
