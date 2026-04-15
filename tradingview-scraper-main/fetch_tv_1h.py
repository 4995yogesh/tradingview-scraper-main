import os, sys, time
sys.path.insert(0, './Trading-Project')
from backend.server import _seed_storage, candle_db, logger
from tradingview_scraper.symbols.historical import HistoricalFetcher

def fetch_tv_1h():
    print("Fetching raw 1H from TradingView...")
    exchange, symbol = "OANDA", "EURUSD"
    tf = '1h'
    
    jwt_value = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
    cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
    
    fetcher = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
    
    older = fetcher.fetch_historical_data(
        exchange=exchange,
        symbol=symbol,
        timeframe=tf,
        limit=50000,
        start_date=None,
        chunk_size=10000,
        delay_ms=250
    )
    
    if older:
        _seed_storage(exchange, symbol, tf, older)
        print(f"Healed {tf} with {len(older)} bars!")

if __name__ == "__main__":
    fetch_tv_1h()
