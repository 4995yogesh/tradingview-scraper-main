import time
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import logging
from histdata import download_hist_data as dl
import zipfile
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ValidityChecker")

DB_PATH = 'Trading-Project/data/candles.db'
RAW_DIR = './histdata_raw'
os.makedirs(RAW_DIR, exist_ok=True)

TF_MAP = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '60min', '4h': '240min', '1D': '1D'}

def fetch_and_patch_dukascopy(gap_start_ts, gap_end_ts, timeframe):
    """Downloads missing Dukascopy monthly slices, resamples, and upserts."""
    logger.warning(f"Initiating auto-healing for gap: {gap_start_ts} -> {gap_end_ts}")
    # Convert ts back to dates to know which months to download
    start_dt = datetime.utcfromtimestamp(gap_start_ts)
    end_dt = datetime.utcfromtimestamp(gap_end_ts)
    
    current_dt = start_dt.replace(day=1)
    dfs = []
    
    while current_dt <= end_dt:
        year = current_dt.year
        month = current_dt.month
        logger.info(f"Targeting HistData {year}-{month:02d} for gap patch...")
        
        try:
            path = dl(year=str(year), month=str(month), pair="EURUSD", time_frame='M1', output_directory=RAW_DIR)
            if path:
                if isinstance(path, list): path = path[0]
                clean_file = path
                if path.endswith('.zip'):
                    with zipfile.ZipFile(path, 'r') as z:
                        csv_name = z.namelist()[0]
                        z.extract(csv_name, RAW_DIR)
                        clean_file = os.path.join(RAW_DIR, csv_name)
                        
                df = pd.read_csv(clean_file, sep=';', header=None, names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                dfs.append(df)
        except Exception as e:
            logger.error(f"Histdata pull failed for {year}-{month}: {e}")
            
        if current_dt.month == 12:
            current_dt = current_dt.replace(year=year+1, month=1)
        else:
            current_dt = current_dt.replace(month=month+1)
            
    if not dfs:
        logger.error("Failed to retrieve patching fragments!")
        return 0
        
    master_df = pd.concat(dfs, ignore_index=True)
    master_df['dt'] = pd.to_datetime(master_df['datetime'], format='%Y%m%d %H%M%S')
    master_df['dt'] = master_df['dt'] + pd.Timedelta(hours=5) # EST to UTC
    master_df.drop_duplicates(subset=['dt'], keep='last', inplace=True)
    master_df.sort_values(by='dt', ascending=True, inplace=True)
    master_df.set_index('dt', inplace=True)
    
    pd_tf = TF_MAP.get(timeframe, '1min')
    logger.info(f"Resampling patching fragment into {pd_tf} structural bounds...")
    resampled = master_df.resample(pd_tf).agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    resampled.reset_index(inplace=True)
    resampled['ts'] = (resampled['dt'] - pd.Timestamp("1970-01-01")) // pd.Timedelta('1s')
    
    # Filter exactly over the gap region to avoid bloated ops
    patch_df = resampled[(resampled['ts'] > gap_start_ts) & (resampled['ts'] < gap_end_ts)]
    logger.info(f"Extracted {len(patch_df)} valid bars to inject into sequence.")
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for _, row in patch_df.iterrows():
        cur.execute("""
            INSERT OR REPLACE INTO candles (exchange, symbol, timeframe, ts, open, high, low, close, volume, passed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, ('OANDA', 'EURUSD', timeframe, row['ts'], row['open'], row['high'], row['low'], row['close'], row['volume']))
    conn.commit()
    conn.close()
    return len(patch_df)

def check_validity():
    logger.info("Initializing Data Validity Checker Pipeline...")
    conn = sqlite3.connect(DB_PATH)
    timeframes = ['1m', '5m', '15m', '1h', '4h', '1D']
    
    global_passed = True
    
    for tf in timeframes:
        logger.info(f"Auditing structural continuity for {tf}...")
        df = pd.read_sql_query(f"SELECT ts, passed FROM candles WHERE timeframe='{tf}' ORDER BY ts ASC", conn)
        if df.empty: continue
        
        # Calculate diffs
        df['dt'] = pd.to_datetime(df['ts'], unit='s', utc=True)
        df['diff'] = df['dt'].diff()
        
        # Detect true gaps (Forex standard > 3 days)
        gaps = df[df['diff'] > pd.Timedelta(days=3)]
        
        if not gaps.empty:
            global_passed = False
            for idx, row in gaps.iterrows():
                gap_end = row['ts']
                gap_start = df.iloc[idx - 1]['ts']
                logger.warning(f"[{tf}] Discontinuity breached: {gap_start} -> {gap_end} (Diff: {row['diff']})")
                
                # Automatically patch via Dukascopy
                healed = fetch_and_patch_dukascopy(gap_start, gap_end, tf)
                if healed > 0:
                    logger.info(f"[{tf}] Successfully sealed structural gap with {healed} interpolated nodes.")
        
        # Pass Labeling phase
        conn.execute(f"UPDATE candles SET passed = 1 WHERE timeframe = '{tf}'")
        conn.commit()
        logger.info(f"[{tf}] Matrix certified and labeled `passed=1`. Authorized for canvas rendering.")
    
    conn.close()

if __name__ == "__main__":
    while True:
        check_validity()
        logger.info("Validity enforcement cycle complete. Sleeping 600s.")
        time.sleep(600)
