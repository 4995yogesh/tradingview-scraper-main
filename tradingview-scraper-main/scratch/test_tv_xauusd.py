import sys
import os
import logging

ROOT = r"c:\Users\ysssi\Desktop\Tradingview_Main\tradingview-scraper-main\tradingview-scraper-main"
sys.path.insert(0, ROOT)

from tradingview_scraper.symbols.historical import HistoricalFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
jwt_value = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")

fetcher = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
try:
    print("Fetching XAUUSD 5m candles...")
    raw_candles = fetcher.fetch_historical_data(
        exchange="OANDA",
        symbol="XAUUSD",
        timeframe="5m",
        limit=5000,
        start_date=None,
        chunk_size=1000,
        delay_ms=250,
    )
    print("Total candles fetched:", len(raw_candles))
    if raw_candles:
        import datetime
        dt_first = datetime.datetime.fromtimestamp(raw_candles[0]['timestamp'], datetime.timezone.utc)
        dt_last = datetime.datetime.fromtimestamp(raw_candles[-1]['timestamp'], datetime.timezone.utc)
        print("First candle time:", dt_first, f"({raw_candles[0]['timestamp']})")
        print("Last candle time:", dt_last, f"({raw_candles[-1]['timestamp']})")
except Exception as e:
    print("Error:", e)
