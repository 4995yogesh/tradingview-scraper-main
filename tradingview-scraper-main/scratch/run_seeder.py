import sys
import logging
from pathlib import Path

# Add backend and Trading-Project directories to python path
project_dir = Path("c:/Users/ysssi/Desktop/Tradingview_Main/tradingview-scraper-main/tradingview-scraper-main/Trading-Project")
sys.path.insert(0, str(project_dir))
sys.path.insert(0, str(project_dir / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

import dukascopy_seeder as ds
from pipeline.data.db import candle_db

print("Running dukascopy_seeder.seed_missing_pairs()...")
ds.seed_missing_pairs(candle_db)
print("Done.")
