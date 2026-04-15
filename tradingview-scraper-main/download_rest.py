import os
import sys
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, './Trading-Project')
from tradingview_scraper.symbols.historical import HistoricalFetcher
from dotenv import load_dotenv

def download_rest():
    load_dotenv()
    jwt_value = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
    cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
    
    # We only need 1h and 4h
    targets = {
        '1h': ('60', 50000),
        '4h': ('240', 20000)
    }
    
    exchange, symbol = "OANDA", "EURUSD"
    os.makedirs("./ohlc_data_pro", exist_ok=True)
    
    for tf_str, (tf_num, limit) in targets.items():
        print(f"Fetching {tf_str} -> numeric {tf_num}")
        fetcher = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
        data = fetcher.fetch_historical_data(
            exchange=exchange, symbol=symbol, timeframe=tf_str,
            limit=limit, start_date=None, chunk_size=10000, delay_ms=250
        )
        if not data: continue
        
        df = pd.DataFrame(data)
        if 'timestamp' in df.columns: df.rename(columns={'timestamp': 'ts'}, inplace=True)
        df.drop_duplicates(subset=["ts"], keep="last", inplace=True)
        df.sort_values(by="ts", ascending=True, inplace=True)
        df.reset_index(drop=True, inplace=True)
        df["datetime_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        csv_path = f"./ohlc_data_pro/{symbol}_{tf_num}.csv"
        df.to_csv(csv_path, index=False)
        print(f"Saved {csv_path} with {len(df)} rows.")

if __name__ == "__main__":
    download_rest()
