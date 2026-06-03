import urllib.request
import json

url = "http://localhost:8000/api/ohlc?exchange=OANDA&symbol=EURUSD&timeframe=1d&candles=500"
try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print(f"Status: {data.get('status')}")
        print(f"Candles count: {len(data.get('candleData', []))}")
        if data.get('status') == 'loading':
            print("BACKEND IS RETURNING LOADING FOR EURUSD!")
except Exception as e:
    print(f"Error: {e}")
