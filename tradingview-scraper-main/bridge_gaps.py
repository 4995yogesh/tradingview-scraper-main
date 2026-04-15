import os, sys, time
sys.path.insert(0, './Trading-Project')
from backend.server import _seed_storage, candle_db, logger
from tradingview_scraper.symbols.historical import HistoricalFetcher
from datetime import datetime
import pytz

def heal_gaps():
    print("Starting exact gap healing...")
    exchange, symbol = "OANDA", "EURUSD"
    timeframes = ['1m', '5m', '15m', '1h', '4h']
    
    jwt_value = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
    cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
    
    conn = candle_db._conn()
    for tf in timeframes:
        print(f"Checking {tf}...")
        gap_res = conn.execute(f"SELECT ts, diff FROM (SELECT ts, ts - lag(ts) OVER (ORDER BY ts ASC) as diff FROM candles WHERE exchange=? AND symbol=? AND timeframe=?) WHERE diff > 864000 ORDER BY diff DESC LIMIT 1", (exchange, symbol, tf)).fetchone()
        
        if gap_res and gap_res[1] is not None:
            gap_end_ts_after = gap_res[0]
            gap_start_ts_before = gap_res[0] - gap_res[1]
            print(f"Found gap for {tf}: length {gap_res[1]} secs. End: {datetime.fromtimestamp(gap_end_ts_after)}, Start: {datetime.fromtimestamp(gap_start_ts_before)}")
            
            fetcher = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
            start_dt = datetime.fromtimestamp(gap_start_ts_before, tz=pytz.UTC)
            
            # Use limit to go deep enough to bridge the gap
            older = fetcher.fetch_historical_data(
                exchange=exchange,
                symbol=symbol,
                timeframe=tf,
                limit=300000,
                start_date=start_dt,
                chunk_size=10000,
                delay_ms=250
            )
            
            if older:
                _seed_storage(exchange, symbol, tf, older)
                print(f"Healed {tf} with {len(older)} bars!")
            else:
                print(f"TV returned zero deeper bars for {tf}")

if __name__ == "__main__":
    heal_gaps()
