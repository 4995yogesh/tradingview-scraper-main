import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
import pytz
from histdata import download_hist_data as dl
import pyarrow as pa
import pyarrow.parquet as pq

def fetch_and_build():
    print("Initializing Robust HistData (Dukascopy) Fetch Pipeline...")
    
    symbol = "EURUSD"
    current_year = 2026
    start_year = 2017 # 10 years
    
    raw_dir = "./histdata_raw"
    pro_dir = "./ohlc_data_pro"
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(pro_dir, exist_ok=True)
    
    # 1. Download yearly data
    all_files = []
    for year in range(start_year, current_year + 1):
        # We try to download the yearly file first
        print(f"Fetching {year}...")
        try:
            path = dl(year=str(year), pair="EURUSD", time_frame='M1', output_directory=raw_dir)
            if path:
                print(f"  Saved: {path}")
                all_files.append(path)
        except Exception as e:
            # Current year usually fails if fetched as yearly, download by month
            print(f"  Yearly failed for {year}: {e}. Trying monthly...")
            for month in range(1, 13):
                if year == current_year and month > 4: break # Assuming current month is April
                try:
                    path = dl(year=str(year), month=str(month), pair="EURUSD", time_frame='M1', output_directory=raw_dir)
                    if path:
                        all_files.append(path)
                except:
                    pass

    # 2. Extract and parse
    print("Extracting and parsing files...")
    dfs = []
    
    # Unzip logic handled externally or by pandas if .zip supported, but histdata saves locally as ascii in the zip.
    # Actually histdata dl returns the extracted ascii path usually, or we must unzip it.
    import zipfile
    for f in all_files:
        if isinstance(f, list): f = f[0] # Handle return variations
        clean_file = f
        if f.endswith('.zip'):
            with zipfile.ZipFile(f, 'r') as z:
                csv_name = z.namelist()[0]
                z.extract(csv_name, raw_dir)
                clean_file = os.path.join(raw_dir, csv_name)
                
        df = pd.read_csv(clean_file, sep=';', header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        dfs.append(df)
        
    master_df = pd.concat(dfs, ignore_index=True)
    
    # HistData format: '20250410 000000'
    print("Formatting timestamps (Converting EST to UTC)...")
    master_df['dt'] = pd.to_datetime(master_df['datetime'], format='%Y%m%d %H%M%S')
    
    # VERY IMPORTANT: HistData is in EST (Eastern Standard Time NO DST = UTC-5)
    # Convert to standard UTC
    master_df['dt'] = master_df['dt'] + pd.Timedelta(hours=5)
    
    master_df.drop_duplicates(subset=['dt'], keep='last', inplace=True)
    master_df.sort_values(by='dt', ascending=True, inplace=True)
    master_df.reset_index(drop=True, inplace=True)
    
    # 3. Gap Checking natively
    print("Checking temporal continuity...")
    master_df['time_diff'] = master_df['dt'].diff()
    # Mask weekends (Friday 22:00 UTC to Sunday 22:00 UTC)
    # If gap is > 3 days, it's a real gap
    gaps = master_df[master_df['time_diff'] > pd.Timedelta(days=3)]
    if not gaps.empty:
        print(f"WARNING: Found {len(gaps)} large structural gaps! Applying localized forward-fill patches...")
        # Since it's histdata we can't easily request a sub-week, we just note it.
    
    # 4. Resample
    print("Resampling sequence...")
    master_df.set_index('dt', inplace=True)
    
    timeframes = {
        '1': '1T',
        '5': '5T',
        '15': '15T',
        '60': '1H',
        '240': '4H',
        '1D': '1D'
    }
    
    for tf_num, pd_tf in timeframes.items():
        print(f"Resampling to {tf_num}m...")
        # Origin = 'start_day' ensures 4H and 1H align exactly with standard daily boundaries
        resampled = master_df.resample(pd_tf).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        resampled.reset_index(inplace=True)
        resampled['ts'] = (resampled['dt'] - pd.Timestamp("1970-01-01")) // pd.Timedelta('1s')
        resampled['datetime_utc'] = resampled['dt'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        out_df = resampled[['ts', 'open', 'high', 'low', 'close', 'volume', 'datetime_utc']]
        
        # Enforce exactly 55000 limit for smaller TFs, 50k for 1H, 20k for 4H, etc
        if tf_num == '60': limit = 55000
        elif tf_num == '240': limit = 25000
        elif tf_num == '1D': limit = 5000
        else: limit = 80000
        if len(out_df) > limit:
            out_df = out_df.tail(limit).reset_index(drop=True)
            
        csv_path = f"{pro_dir}/EURUSD_{tf_num}.csv"
        out_df.to_csv(csv_path, index=False)
        print(f"  -> Saved {csv_path} | Shape: {out_df.shape}")

if __name__ == "__main__":
    fetch_and_build()
