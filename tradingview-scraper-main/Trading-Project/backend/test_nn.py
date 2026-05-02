import sys
sys.path.insert(0, 'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend')
from ml.nn_scorer import predict_box, load_nn_model
import json

load_nn_model()
ctx = json.loads('[{"time": "2026-04-30T05:15:00Z", "open": 1.16635, "high": 1.16642, "low": 1.16618, "close": 1.16632, "volume": 295.0}, {"time": "2026-04-30T05:20:00Z", "open": 1.16632, "high": 1.16644, "low": 1.16625, "close": 1.16639, "volume": 361.0}]')
res = predict_box(ctx)
print("PREDICT_BOX RESULT:", res)
