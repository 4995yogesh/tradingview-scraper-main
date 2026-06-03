import sys
import os
import time
import logging

# Setup search paths to match the server environment
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_DIR = os.path.join(ROOT_DIR, "Trading-Project")
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")

sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("downloader")

from tradingview_scraper.symbols.historical import HistoricalFetcher
from pipeline.data.db import candle_db

# Seeding plan using TradingView's deep history
SEEDS = [
    ("1w", 2000),
    ("1d", 5000),
    ("4h", 10000),
    ("1h", 10000),
    ("15m", 15000),
    ("5m", 15000),
    ("1m", 15000),
]

def download_xauusd():
    logger.info("=== Starting sequential TradingView historical download for XAUUSD ===")
    
    exchange = "OANDA"
    symbol = "XAUUSD"
    
    cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
    jwt_value = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
    
    for timeframe, limit in SEEDS:
        logger.info(f"--- Fetching {exchange}:{symbol} [{timeframe}] (limit: {limit}) ---")
        
        # Instantiate a fresh fetcher per timeframe to ensure clean session state
        fetcher = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
        
        try:
            # Fetch historical data
            raw_candles = fetcher.fetch_historical_data(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                chunk_size=5000,
                delay_ms=500, # Conservative delay to prevent rate limits
            )
            
            if raw_candles:
                logger.info(f"Successfully fetched {len(raw_candles)} candles. Writing to DB...")
                candle_db.upsert_candles(exchange, symbol, timeframe, raw_candles)
                
                # Verify DB count
                new_count = candle_db.count(exchange, symbol, timeframe)
                logger.info(f"Verified: {exchange}:{symbol} [{timeframe}] total DB count is now {new_count}")
            else:
                logger.warning(f"No candles returned for {timeframe}")
                
        except Exception as e:
            logger.error(f"Failed to download/write {timeframe}: {e}")
            
        # Delay between timeframes to respect rate-limiting
        time.sleep(2.0)
        
    logger.info("=== Historical download task completed successfully ===")

if __name__ == "__main__":
    download_xauusd()
