import sys
import os
import time
from pathlib import Path

# Add project roots
ROOT_DIR = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main"
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, "Trading-Project"))

from tradingview_scraper.symbols.historical import HistoricalFetcher
from pipeline.data.db import candle_db

def fetch_usdjpy():
    exchange = "OANDA"
    symbol = "USDJPY"
    timeframe = "15m"
    limit = 2000 # Smaller limit to ensure it finishes and commits
    
    print(f"Fetching {limit} candles for {exchange}:{symbol} [{timeframe}]...")
    
    fetcher = HistoricalFetcher()
    try:
        # Fetch data
        candles = fetcher.fetch_historical_data(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )
        
        if not candles:
            print("No candles fetched.")
            return

        print(f"Fetched {len(candles)} candles. Sample: {candles[0]}")
        print("Upserting to CandleDB...")
        
        # Upsert to DB
        candle_db.upsert_candles(exchange, symbol, timeframe, candles)
        print("Done.")
        
    except Exception as e:
        print(f"Fetch failed: {e}")

if __name__ == "__main__":
    fetch_usdjpy()
