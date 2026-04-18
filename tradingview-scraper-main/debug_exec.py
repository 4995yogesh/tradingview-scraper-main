import sys, os, pickle, sqlite3
import numpy as np
import pandas as pd

# Root dir
ROOT = os.path.abspath(os.getcwd())
PROJECT = os.path.join(ROOT, 'Trading-Project', 'project')
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(ROOT, 'Trading-Project'))

print('--- DEBUG START ---')
try:
    with open('Trading-Project/project/ml/consolidation_scorer/model.pkl', 'rb') as f:
        d = pickle.load(f)
    print(f"[TASK 6] Threshold: {d.get('optimal_threshold', 'N/A')}")
    model = d['model']
    feature_cols = d['feature_cols']
    if hasattr(model, 'feature_importances_'):
        imps = sorted(zip(feature_cols, model.feature_importances_), key=lambda x: x[1], reverse=True)
        print(f"[TASK 4] Top Importance: {imps[:5]}")

    fb_db = 'Trading-Project/backend/data/ml_feedback.db'
    if os.path.exists(fb_db):
        conn = sqlite3.connect(fb_db)
        # Use total labels including GOOD/BAD
        dist = conn.execute("SELECT user_label, count(*) FROM boxes WHERE user_label IN ('GOOD', 'BAD') GROUP BY user_label").fetchall()
        total = sum(d[1] for d in dist)
        conn.close()
        print(f"[TASK 7] Samples: {total}")
        print(f"[TASK 3] Label Dist: {dist}")

    from indicators.consolidation import consolidation_boxes
    from project.ml.consolidation_scorer.features import build_feature_matrix
    
    db_path = 'Trading-Project/data/candles.db'
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        df_ohlc = pd.read_sql_query("SELECT * FROM candles WHERE timeframe='1h' ORDER BY ts DESC LIMIT 800", conn)
        conn.close()
        if not df_ohlc.empty:
            df_ohlc['datetime'] = pd.to_datetime(df_ohlc['ts'], unit='s', utc=True)
            df_ohlc = df_ohlc.set_index('datetime').sort_index()

            boxes = consolidation_boxes(df_ohlc, min_bars=5)
            if not boxes.empty:
                feats = build_feature_matrix(df_ohlc, boxes, timeframe='1h')
                std = feats[feature_cols].std()
                print(f"[TASK 2] Std Dev Range: {std.min():.4f} to {std.max():.4f}")
                
                X = feats[feature_cols].astype(np.float32)
                for col in feature_cols:
                    fill = d.get('col_medians', {}).get(col, 0.0)
                    X[col] = X[col].replace([np.inf, -np.inf], np.nan).fillna(fill)
                
                preds = np.clip(model.predict(X), 0.0, 1.0)
                print(f"[TASK 1] Pred Stats: min={preds.min():.4f}, max={preds.max():.4f}, avg={preds.mean():.4f}")
                print(f"[TASK 5] Samples: {preds[:10].tolist()}")
            else:
                print('No recent boxes found to score')
except Exception as e:
    import traceback
    traceback.print_exc()
print('--- DEBUG END ---')
