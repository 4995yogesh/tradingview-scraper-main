import sys
import os
import json
import time
import urllib.request

# Path setup
BACKEND_DIR = os.path.join(os.getcwd(), "Trading-Project", "backend")
sys.path.append(BACKEND_DIR)

from ml.quality.autolabel.auto_labeller import auto_label_pipeline
from ml.quality.db import save_auto_label
from ml.quality.features import QualityExtractor

# Simple cache for candles
CANDLE_CACHE = {}

def fetch_candles_proxy(exchange, symbol, tf, count=1000):
    cache_key = f"{exchange}:{symbol}:{tf}"
    if cache_key in CANDLE_CACHE:
        return CANDLE_CACHE[cache_key]
        
    try:
        url = f"http://localhost:8000/api/ohlc?exchange={exchange}&symbol={symbol}&timeframe={tf}&candles={count}"
        resp = urllib.request.urlopen(url)
        data = json.loads(resp.read().decode())
        candles = data.get('candleData', [])
        CANDLE_CACHE[cache_key] = candles
        return candles
    except Exception as e:
        print(f"Fetch error: {e}")
        return []

class SmartMockGemini:
    def generate_content(self, prompt):
        # Dynamically determine structure based on feature presence in prompt string
        # Production Gemini would parse the actual features; here we simulate variance
        is_high_quality = "\"behavior_score\": 0.4" in prompt or "\"movement_efficiency\": 0.9" in prompt
        is_low_quality = "\"structure_penalty\": 0.5" in prompt
        
        class Resp:
            def __init__(self, high, low):
                if high:
                    res = {
                        "interpretation": "Structure shows exceptional boundary respect and high internal efficiency.",
                        "structure_type": "balanced",
                        "confidence": 0.92
                    }
                elif low:
                    res = {
                        "interpretation": "Erratic price action with high structure penalty and drifting behavior.",
                        "structure_type": "drifting",
                        "confidence": 0.78
                    }
                else:
                    res = {
                        "interpretation": "Standard consolidation with stable but unremarkable structural features.",
                        "structure_type": "balanced",
                        "confidence": 0.65
                    }
                self.text = json.dumps(res)
        return Resp(is_high_quality, is_low_quality)

def run_auto_label_job():
    print("Fetching live consolidations...")
    try:
        resp = urllib.request.urlopen("http://localhost:8000/consolidations")
        data = json.loads(resp.read().decode())
        zones = data.get("zones", [])
    except Exception as e:
        print(f"Fetch error: {e}")
        return

    # Filter to unique box_ids to avoid redundant processing
    seen_ids = set()
    unique_zones = []
    for z in zones:
        bid = z.get('box_id')
        if bid and bid not in seen_ids:
            seen_ids.add(bid)
            unique_zones.append(z)

    print(f"Processing {len(unique_zones)} unique zones with Smart Mock Logic...")
    
    extractor = QualityExtractor(fetch_candles_proxy)
    gemini = SmartMockGemini()
    
    # Process in batches to show progress
    batch_size = 50
    for i in range(0, len(unique_zones), batch_size):
        batch = unique_zones[i:i+batch_size]
        results = auto_label_pipeline(batch, extractor, gemini)
        
        for r in results:
            save_auto_label(
                r['box_id'], r['label'], r['confidence'], r['status'], 
                r['approved'], r['reason'], r['start'], r['end']
            )
        print(f"Progress: {min(i+batch_size, len(unique_zones))}/{len(unique_zones)}")
    
    print(f"Done. Refreshing chart cache...")
    try: urllib.request.urlopen("http://localhost:8000/api/repair")
    except: pass

if __name__ == "__main__":
    run_auto_label_job()
