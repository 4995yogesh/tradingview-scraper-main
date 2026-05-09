import sys
import os
import json
from datetime import datetime

# Path setup
TRADING_PROJECT_DIR = os.path.abspath(os.path.join(os.getcwd(), "Trading-Project"))
sys.path.insert(0, TRADING_PROJECT_DIR)
sys.path.insert(0, os.path.join(TRADING_PROJECT_DIR, "backend"))
sys.path.insert(0, os.path.join(TRADING_PROJECT_DIR, "project"))

from pipeline.data.storage import storage
from indicators.consolidation import consolidation_boxes
from ml.nn_scorer import predict_box, load_nn_model, is_nn_ready
from server import _load_db_into_ram, PERSISTENT_TIMEFRAMES
import pandas as pd

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "localization_results_log.json")

def log_result(symbol, timeframe, results):
    log_data = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                log_data = json.load(f)
        except: pass
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "results": results
    }
    log_data.append(log_entry)
    
    with open(LOG_FILE, 'w') as f:
        json.dump(log_data, f, indent=2)
    print(f"Logged {len(results)} results to {LOG_FILE}")

def test_symbol(symbol="USDJPY", timeframe="5m"):
    print(f"--- Testing {symbol} {timeframe} ---")
    
    # 1. Ensure RAM is seeded from DB
    _load_db_into_ram("OANDA", symbol, timeframe)
    candles = storage.get_candles("OANDA", symbol, timeframe, count=1000)
    if not candles:
        print(f"No candles found for {symbol} {timeframe}")
        return
    
    df = pd.DataFrame(candles)
    if 'time' in df.columns:
        unit = 'ms' if df['time'].iloc[0] > 1e11 else 's'
        df['time'] = pd.to_datetime(df['time'], unit=unit)
        df.set_index('time', inplace=True)
    
    # 2. Get heuristic zones
    zones = consolidation_boxes(df).to_dict('records')
    if not zones:
        print("No heuristic zones found.")
        return
    
    # Take last 5 zones
    test_zones = zones[-5:]
    print(f"Found {len(test_zones)} zones to refine.")
    
    load_nn_model()
    
    results = []
    for i, zone in enumerate(test_zones):
        z_start = int(zone['start'])
        z_end = int(zone['end'])
        
        # Window alignment (30 candles buffer)
        ctx_end = min(len(df) - 1, z_end + 30)
        ctx_start = max(0, ctx_end - 100)
        
        ohlc_slice_df = df.iloc[ctx_start : ctx_end].copy()
        ohlc_slice = ohlc_slice_df.reset_index().to_dict('records')
        
        # Convert times for predictor
        for c in ohlc_slice:
            if hasattr(c['time'], 'timestamp'):
                c['time'] = c['time'].timestamp()
        
        nn_box = predict_box(ohlc_slice)
        
        res = {
            "zone_index": i,
            "heuristic": {
                "start_idx": z_start,
                "end_idx": z_end,
                "priceHigh": zone['top'],
                "priceLow": zone['bottom']
            },
            "ml_refined": nn_box if nn_box else "FAILED"
        }
        results.append(res)
        
        if nn_box:
            # Check relative offset from heuristic end
            # nn_box['timeEnd'] should be close to df.index[z_end]
            h_end_ts = df.index[z_end].timestamp()
            ml_end_ts = nn_box['timeEnd']
            offset = ml_end_ts - h_end_ts
            print(f"Zone {i}: Offset: {offset:.1f}s")
    
    log_result(symbol, timeframe, results)

if __name__ == "__main__":
    test_symbol("EURUSD", "5m")
    test_symbol("USDJPY", "5m")
    test_symbol("USDJPY", "15m")
