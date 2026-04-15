import os
import sys
import time
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, './Trading-Project')
from tradingview_scraper.symbols.historical import HistoricalFetcher
from dotenv import load_dotenv

def download_all():
    print("Downloading TRUE TradingView Data directly...")
    load_dotenv()
    
    jwt_value = os.getenv("TV_JWT_TOKEN", "unauthorized_user_token")
    cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()
    
    # Target bars for each timeframe mapping (str to pass to fetcher -> numerical for file name)
    targets = {
        '1m': ('1', 55000),
        '5m': ('5', 55000),
        '15m': ('15', 55000),
        '1h': ('60', 50000),
        '4h': ('240', 20000)
    }
    
    exchange, symbol = "OANDA", "EURUSD"
    
    os.makedirs("./ohlc_data_pro", exist_ok=True)
    
    for tf_str, (tf_num, limit) in targets.items():
        print(f"Fetching {tf_str} (Target: {limit} bars)")
        
        fetcher = HistoricalFetcher(websocket_jwt_token=jwt_value, cookie=cookie_value)
        data = fetcher.fetch_historical_data(
            exchange=exchange,
            symbol=symbol,
            timeframe=tf_str,
            limit=limit,
            start_date=None,
            chunk_size=10000,
            delay_ms=250
        )
        
        if not data:
            print(f"WARNING: Got 0 bars for {tf_str}")
            continue
            
        print(f"Received {len(data)} bars for {tf_str}")
        
        # Format DataFrame just like alt_fetcher
        df = pd.DataFrame(data)
        if 'timestamp' in df.columns:
            df.rename(columns={'timestamp': 'ts'}, inplace=True)
            
        # Convert to strict order
        df.drop_duplicates(subset=["ts"], keep="last", inplace=True)
        df.sort_values(by="ts", ascending=True, inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        df["datetime_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        csv_path = f"./ohlc_data_pro/{symbol}_{tf_num}.csv"
        pq_path = f"./ohlc_data_pro/{symbol}_{tf_num}.parquet"
        
        df.to_csv(csv_path, index=False)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, pq_path)
        print(f"Saved {csv_path} with {len(df)} rows.")

if __name__ == "__main__":
    download_all()
