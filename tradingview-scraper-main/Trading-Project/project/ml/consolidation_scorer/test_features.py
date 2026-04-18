import pandas as pd
import numpy as np
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ml.consolidation_scorer.features import extract_features

# Mock OHLC data
df = pd.DataFrame({
    "open": np.random.rand(100) + 10,
    "high": np.random.rand(100) + 11,
    "low": np.random.rand(100) + 9,
    "close": np.random.rand(100) + 10,
    "volume": np.random.rand(100) * 1000
})

box = pd.Series({
    "start": 10,
    "end": 30,
    "top": 11.5,
    "bottom": 9.5
})

try:
    feats = extract_features(df, box, timeframe="1h")
    if feats:
        print(f"SUCCESS: Extracted {len(feats)} features")
        for k, v in list(feats.items())[:5]:
            print(f"  {k}: {v}")
    else:
        print("FAILED: No features extracted")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
