import numpy as np
import lightgbm as lgb
from sklearn.metrics import mean_squared_error
from ml.quality.db import get_all_samples, get_conn, DB_PATH
from ml.quality.features import FEATURE_NAMES
import os
import json
import time

def train_quality_model():
    """
    Train a regression model using time-based split.
    """
    samples = get_all_samples()
    if len(samples) < 10:
        print(f"Not enough samples to train ({len(samples)})")
        return None

    # samples are sorted by created_at ascending in DB
    X = []
    y = []
    for s in samples:
        X.append(json.loads(s['features']))
        y.append(s['label_score'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Time-based split: 80/20
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    params = {
        "objective": "regression",
        "metric": "rmse",
        "n_estimators": 300,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "feature_fraction": 0.8,
        "min_data_in_leaf": 10,
        "reg_alpha": 0.05,
        "reg_lambda": 0.8,
        "min_gain_to_split": 0.05,
        "verbose": -1,
        "seed": 42
    }
    
    train_data = lgb.Dataset(X_train, label=y_train)
    test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)
    
    model = lgb.train(
        params,
        train_data,
        valid_sets=[test_data],
        callbacks=[lgb.early_stopping(stopping_rounds=20)]
    )
    
    y_pred = model.predict(X_test)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    
    print(f"Quality Model RMSE: {rmse:.4f}")
    
    # Feature Importance
    importance = model.feature_importance(importance_type='gain')
    sorted_idx = np.argsort(importance)[::-1]
    
    top_10 = [FEATURE_NAMES[i] for i in sorted_idx[:10]]
    print("\nTop 10 Feature Importance:")
    for i in sorted_idx[:10]:
        print(f"{FEATURE_NAMES[i]}: {importance[i]:.2f}")
        
    # SECTION 7 - Debug (Mandatory Mean Values)
    ext_idx = {name: FEATURE_NAMES.index(name) for name in ["behavior_score", "structure_penalty", "movement_efficiency", "rejection_rate", "boundary_time_ratio"]}
    print("\nBehavioral Features Mean Values:")
    for name, idx in ext_idx.items():
        print(f"  {name}: {np.mean(X[:, idx]):.4f}")

    # SECTION 8 - Validation (Strict Rule)
    top_3 = top_10[:3]
    if not any(f in top_3 for f in ["behavior_score", "movement_efficiency", "rejection_rate"]):
        print("\nWARNING: Model still not behavior-dominant")
        
    # False Positives Analysis
    # Predicted GOOD (>= 0.75) but actual BAD (< 0.5)
    fp_indices = []
    for i in range(len(y_test)):
        if y_pred[i] >= 0.75 and y_test[i] < 0.5:
            fp_indices.append(i)
            
    print(f"\nFalse Positives (Predicted VG/G but actually B/VB): {len(fp_indices)}")
    
    # Save model
    model_dir = os.path.join(os.path.dirname(DB_PATH), "quality_models")
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "quality_lgb_v1.txt")
    model.save_model(model_path)
    
    return model
