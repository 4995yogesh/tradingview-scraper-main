import requests
import json

url = "http://localhost:8000/api/ohlc?exchange=OANDA&symbol=XAUUSD&timeframe=5m&candles=500"
try:
    resp = requests.get(url, timeout=5)
    print(f"Status code: {resp.status_code}")
    data = resp.json()
    print(f"JSON Keys: {list(data.keys())}")
    print(f"Response status: {data.get('status')}")
    candle_data = data.get('candleData', [])
    print(f"Number of candles returned: {len(candle_data)}")
    if candle_data:
        print("First candle:", candle_data[0])
        print("Last candle:", candle_data[-1])
except Exception as e:
    print("Error calling API:", e)
