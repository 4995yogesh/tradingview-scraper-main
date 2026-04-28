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
    print("--- SECTION 1: DATA INTEGRITY ---")
    
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
    count = 0
    for bid in relabelled[:5]:
        history = [l for l in labels if l['box_id'] == bid]
        history.sort(key=lambda x: x['created_at'])
        print(f"\nBox ID: {bid}")
        for i, entry in enumerate(history):
            status = "BEFORE" if i == 0 else f"AFTER {i}"
            print(f"  {status}: Label={entry['label']}, Created={entry['created_at']}")
    
    print("\n--- SECTION 2: FEATURE VALIDATION ---")
    quality_samples = get_quality_samples()
    df = pd.DataFrame([json.loads(s['features']) for s in quality_samples], columns=FEATURE_NAMES)
    df['label_score'] = [s['label_score'] for s in quality_samples]
    df['box_id'] = [s['box_id'] for s in quality_samples]
    
    # 4. FP vs GOOD correct Correct Samples
    # We need a trained model to find FPs
    import lightgbm as lgb
    from sklearn.metrics import mean_squared_error
    
    X = df[FEATURE_NAMES].values
    y = df['label_score'].values
    
    model = lgb.Booster(model_file=os.path.join(os.path.dirname(QUALITY_DB_PATH), "quality_models", "quality_lgb_v1.txt"))
    preds = model.predict(X)
    df['pred'] = preds
    
    # FP: Pred >= 0.75, Actual < 0.5
    fps = df[(df['pred'] >= 0.75) & (df['label_score'] < 0.5)].head(3)
    # Correct Good: Pred >= 0.75, Actual >= 0.75
    goods = df[(df['pred'] >= 0.75) & (df['label_score'] >= 0.75)].head(3)
    
    print("\nFP Examples vs Correct GOOD (Difference Analysis):")
    for i in range(min(len(fps), len(goods))):
        fp_row = fps.iloc[i]
        good_row = goods.iloc[i]
        print(f"\nPair {i+1}:")
        print(f"  FP (Actual={fp_row['label_score']:.2f}, Pred={fp_row['pred']:.2f})")
        print(f"  GOOD (Actual={good_row['label_score']:.2f}, Pred={good_row['pred']:.2f})")
        
        diff = np.abs(fp_row[FEATURE_NAMES].values.astype(float) - good_row[FEATURE_NAMES].values.astype(float))
        diff_df = pd.Series(diff, index=FEATURE_NAMES).sort_values(ascending=False)
        print("  Top 5 differences:")
        print(diff_df.head(5))

    print("\n--- Feature Stats (Normalization Check) ---")
    stats = df[FEATURE_NAMES].describe().loc[['min', 'max', 'mean']]
    print(stats.to_string())
    
    # 8. Low variance
    variances = df[FEATURE_NAMES].var()
    low_var = variances[variances < 0.0001]
    print("\nLow Variance Features (< 0.0001):")
    print(low_var if not low_var.empty else "None")

    print("\n--- SECTION 3: TRAINING PIPELINE ---")
    print("9. Retrained from scratch? YES (lgb.train starts from Dataset each time)")
    print("10. Caching? NO (Data fetched from SQLite and features extracted per candle batch)")
    print("11. Calibration? NO (Regression model, no probability output)")
    print("12. Sample weights? NO (Not implemented)")

    print("\n--- SECTION 4: MODEL BEHAVIOR ---")
    print(f"15. Feature Importance (Top 10):")
    importance = model.feature_importance(importance_type='gain')
    imp_df = pd.Series(importance, index=FEATURE_NAMES).sort_values(ascending=False)
    print(imp_df.head(10))

    print("\n--- SECTION 5: DATA SUFFICIENCY ---")
    print("17. Class distribution:")
    dist = {
        "VERY_BAD (<0.25)": len(df[df['label_score'] < 0.25]),
        "BAD (0.25-0.5)": len(df[(df['label_score'] >= 0.25) & (df['label_score'] < 0.5)]),
        "GOOD (0.5-0.75)": len(df[(df['label_score'] >= 0.5) & (df['label_score'] < 0.75)]),
        "VERY_GOOD (>0.75)": len(df[df['label_score'] >= 0.75]),
    }
    for k, v in dist.items():
        print(f"  {k}: {v}")

    print("\n--- SECTION 6: FAILURE ANALYSIS (Nearest Neighbor) ---")
    for i, fp_row in fps.iterrows():
        fp_vec = fp_row[FEATURE_NAMES].values.astype(float)
        # Distances to all GOOD samples
        good_pool = df[df['label_score'] >= 0.75]
        dists = np.linalg.norm(good_pool[FEATURE_NAMES].values - fp_vec, axis=1)
        min_idx = np.argmin(dists)
        min_dist = dists[min_idx]
        
        # Distances to all BAD samples (besides itself)
        bad_pool = df[df['label_score'] < 0.5]
        bad_dists = np.linalg.norm(bad_pool[FEATURE_NAMES].values - fp_vec, axis=1)
        # remove self
        bad_dists = bad_dists[bad_dists > 0]
        min_bad_dist = np.min(bad_dists) if len(bad_dists) > 0 else np.inf

        print(f"FP {fp_row['box_id']}:")
        print(f"  Distance to nearest GOOD: {min_dist:.6f}")
        print(f"  Distance to nearest BAD:  {min_bad_dist:.6f}")
        if min_dist < min_bad_dist:
            print("  STUCK: Closer to GOOD class in feature space!")

if __name__ == "__main__":
    run_diagnosis()
