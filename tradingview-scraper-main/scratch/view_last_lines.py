import os
from pathlib import Path

log_path = Path("c:/Users/ysssi/Desktop/Tradingview_Main/tradingview-scraper-main/tradingview-scraper-main/launcher_debug.log")
if log_path.exists():
    lines = log_path.read_text(errors='replace').splitlines()
    print(f"Total lines: {len(lines)}")
    for line in lines[-50:]:
        print(line)
else:
    print("Log file not found.")
