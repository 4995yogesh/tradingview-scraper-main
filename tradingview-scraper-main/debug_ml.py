import sys, os, sqlite3, pickle
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath('Trading-Project'))
sys.path.insert(0, os.path.abspath('Trading-Project/backend/data'))

print("=======================================")
# Load Model
model_path = 'Trading-Project/project/ml/consolidation_scorer/model.pkl'
with open(model_path, 'rb') as f:
    d = pickle.load(f)

model = d.get('model')
print(f"Model Type: {type(model)}")

print("\n--- TASK 4: Feature Importance ---")
if hasattr(model, 'feature_importances_'):
    imps = sorted(zip(d['feature_cols'], model.feature_importances_), key=lambda x: x[1], reverse=True)
    for k, v in imps[:10]:
        print(f"{k}: {v:.4f}")
else:
    print("No feature_importances_ found")

print("\n--- TASK 6: Thresholds ---")
print("GOOD_THRESHOLD (optimal):", d.get('optimal_threshold', 0.5))

print("\n--- TASK 3: Label Distribution ---")
fb_db = 'Trading-Project/backend/data/ml_feedback.db'
if os.path.exists(fb_db):
    try:
        conn = sqlite3.connect(fb_db)
        df_labels = pd.read_sql_query("SELECT user_label FROM boxes WHERE user_label IN ('GOOD', 'BAD')", conn)
        conn.close()
        print(df_labels['user_label'].value_counts(normalize=True))
        print(f"Total training samples available: {len(df_labels)}")
    except Exception as e:
        print("Error reading labels:", e)
else:
    print("ml_feedback.db not found")

print("\n--- TASK 1, 2, 5: Run Inference on latest samples ---")
try:
    from indicators.consolidation import consolidation_boxes
    from project.ml.consolidation_scorer.scorer import ConsolidationScorer

    scorer = ConsolidationScorer()

    db_path = 'Trading-Project/data/candles.db'
    conn = sqlite3.connect(db_path)
    df_ohlc = pd.read_sql_query("SELECT * FROM candles WHERE timeframe='15m' ORDER BY ts DESC LIMIT 2000", conn)
    conn.close()
    
    df_ohlc['datetime'] = pd.to_datetime(df_ohlc['ts'], unit='s', utc=True)
    df_ohlc = df_ohlc.set_index('datetime').sort_index()

    boxes_df = consolidation_boxes(df_ohlc, min_bars=5)
    
    if boxes_df.empty:
        print("No boxes found in last 2000 candles")
    else:
        # Build feature matrix manually to see feature variation
        from project.ml.consolidation_scorer.features import build_feature_matrix
        feat_df = build_feature_matrix(df_ohlc, boxes_df, timeframe="15m")
        print("\n--- TASK 2: Feature Std Dev ---")
        if not feat_df.empty:
            std_devs = feat_df[d['feature_cols']].std()
            print(std_devs.sort_values().head(15)) # show the ones closest to 0
            
            # fill nan
            X = feat_df[d['feature_cols']].astype(np.float32)
            for col in d['feature_cols']:
                fill_val = d.get("col_medians", {}).get(col, 0.0)
                X[col] = X[col].replace([np.inf, -np.inf], np.nan).fillna(fill_val)
            
            preds = model.predict(X)
            preds = np.clip(preds, 0.0, 1.0)
            print("\n--- TASK 1: Prediction Distribution ---")
            print(f"min={preds.min():.4f}, max={preds.max():.4f}, mean={preds.mean():.4f}, len={len(preds)}")
            
            print("\n--- TASK 5: Raw predictions ---")
            print(preds[:20])

except Exception as e:
    import traceback
    traceback.print_exc()

print("=======================================")
