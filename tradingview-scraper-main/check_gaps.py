import sqlite3
import pandas as pd
from pathlib import Path

db_path = Path('Trading-Project/data/candles.db')
conn = sqlite3.connect(db_path)

timeframes = ['1m', '5m', '15m', '1h', '4h']
# Standard expected interval in seconds
tf_intervals = {
    '1m': 60,
    '5m': 300,
    '15m': 900,
    '1h': 3600,
    '4h': 14400
}

# Weekends usually cause a gap. Friday 5 PM EST to Sunday 5 PM EST is  48 hours
max_allowed_gaps = {
    '1m': 60 * 60 * 48 * 2, # ~4 days to be safe for holidays
    '5m': 300 * 2000,
    '15m': 900 * 24 * 5, 
    '1h': 3600 * 24 * 5, # 5 days 
    '4h': 14400 * 24 * 5
}

print("=== CANDLE CONTINUITY CHECK ===")
for tf in timeframes:
    expected = tf_intervals[tf]
    df = pd.read_sql(f"SELECT ts FROM candles WHERE timeframe='{tf}' ORDER BY ts ASC", conn)
    diffs = df['ts'].diff()
    
    # Analyze jumps
    # We ignore the first NaN
    valid_diffs = diffs.dropna()
    
    # Are there any negative diffs? (out of order - should be impossible with ORDER BY ts ASC)
    if (valid_diffs < 0).any():
        print(f"[{tf}] ERROR: Timestamps go backwards!")
    
    # Analyze structural jumps (not exact multiple of the interval!)
    remainder = valid_diffs % expected
    structural_jumps = valid_diffs[(remainder != 0)]
    
    # Large gaps (larger than 4 days = weekend + holiday)
    large_gaps = valid_diffs[valid_diffs > (86400 * 4)]
    
    print(f"\n--- TIMEFRAME: {tf} ---")
    print(f"Total Candles: {len(df)}")
    if len(df) > 0:
        print(f"Date Range: {pd.to_datetime(df['ts'].min(), unit='s')} to {pd.to_datetime(df['ts'].max(), unit='s')}")
    
    if len(structural_jumps) > 0:
        print(f"!!! FOUND {len(structural_jumps)} STRUCTURAL MISALIGNMENTS !!!")
        print(structural_jumps.value_counts().head(5))
    else:
        print("Consistency: Perfect structural alignment (no sub-interval offsets)")
    
    if len(large_gaps) > 0:
        print(f"!!! FOUND {len(large_gaps)} LARGE GAPS (> 4 days) !!!")
        # Find the specific dates
        gap_indices = large_gaps.index
        for idx in list(gap_indices)[:5]: # Show first 5
            t1 = df['ts'].iloc[idx-1]
            t2 = df['ts'].iloc[idx]
            dt1 = pd.to_datetime(t1, unit='s')
            dt2 = pd.to_datetime(t2, unit='s')
            gap_days = (t2 - t1) / 86400.0
            print(f"  Gap: {dt1}  ->  {dt2} ({gap_days:.2f} days)")
        if len(large_gaps) > 5:
            print(f"  ... and {len(large_gaps) - 5} more.")
    else:
        print("Continuity: No massive gaps detected.")

conn.close()
