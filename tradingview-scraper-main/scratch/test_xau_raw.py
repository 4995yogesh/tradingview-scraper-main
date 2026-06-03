import sys
sys.path.insert(0, r"c:\Users\ysssi\Desktop\Tradingview_Main\tradingview-scraper-main\tradingview-scraper-main\Trading-Project\backend")

import dukascopy_seeder as ds
from datetime import date

print("Downloading raw candles for XAUUSD on 2026-05-29...")
raw_1m = ds._fetch_day_1m("XAUUSD", date(2026, 5, 29))
if raw_1m:
    print(f"Fetched {len(raw_1m)} records.")
    print("First 5 raw records:")
    for r in raw_1m[:5]:
        print(f"  ts={r['ts']} o_raw={r['open_raw']} h_raw={r['high_raw']} l_raw={r['low_raw']} c_raw={r['close_raw']}")
else:
    print("No records found.")
