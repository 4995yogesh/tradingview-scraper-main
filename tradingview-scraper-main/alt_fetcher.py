import os
import glob
import zipfile
import logging
import pandas as pd
from datetime import datetime
from histdata import download_hist_data

class AltFetcher:
    """Bypasses TradingView limits using HistData archives for massive historical 1M data sweeps."""
    
    def __init__(self, symbol="EURUSD", output_dir="./ohlc_data_pro", target_bars=55000):
        self.symbol = symbol.lower()
        self.output_dir = output_dir
        self.raw_dir = os.path.join(output_dir, "histdata_raw")
        self.target_bars = target_bars
        self.timeframes = {"1": "1min", "5": "5min", "15": "15min", "60": "1h", "240": "4h"}
        
        os.makedirs(self.raw_dir, exist_ok=True)
        self.logger = logging.getLogger("AltFetcher")

    def _download_years(self, num_years=15):
        current_year = datetime.now().year
        for y in range(current_year - num_years, current_year + 1):
            try:
                self.logger.info(f"Downloading HistData {self.symbol.upper()} for year {y}")
                download_hist_data(
                    year=str(y),
                    pair=self.symbol,
                    time_frame='M1',
                    platform='ASCII',
                    output_directory=self.raw_dir
                )
            except Exception as e:
                self.logger.warning(f"Error or missing year {y}: {e}")

    def _parse_and_merge(self) -> pd.DataFrame:
        zips = glob.glob(os.path.join(self.raw_dir, "*.zip"))
        chunks = []
        
        for z in zips:
            try:
                with zipfile.ZipFile(z, 'r') as archive:
                    csv_name = archive.namelist()[0]
                    with archive.open(csv_name) as f:
                        df = pd.read_csv(
                            f, 
                            sep=';', 
                            names=["timestamp", "open", "high", "low", "close", "volume"]
                        )
                        df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y%m%d %H%M%S")
                        chunks.append(df)
            except Exception as e:
                self.logger.error(f"Failed to extract {z}: {e}")

        if not chunks:
            return pd.DataFrame()

        self.logger.info("Concatenating massive temporal dataframe...")
        master_df = pd.concat(chunks, ignore_index=True)
        master_df.sort_values(by="timestamp", ascending=True, inplace=True)
        master_df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
        
        # Enforce UTC timezone consistency matching previous pipelines
        master_df["timestamp"] = master_df["timestamp"].dt.tz_localize("UTC")
        master_df["datetime_utc"] = master_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        master_df["ts"] = (master_df["timestamp"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().astype('int64')
        
        master_df.set_index("timestamp", inplace=True)
        return master_df

    def resample_and_save(self, master_df: pd.DataFrame):
        for tf, pandas_rule in self.timeframes.items():
            self.logger.info(f"Resampling master dataset structurally to {tf}m")
            
            resampled = master_df.resample(pandas_rule).agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()

            resampled.reset_index(inplace=True)
            resampled["datetime_utc"] = resampled["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
            resampled["ts"] = (resampled["timestamp"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().astype('int64')
            
            # Reorder identically
            resampled = resampled[["ts", "datetime_utc", "open", "high", "low", "close", "volume"]]
            
            final_df = resampled.tail(self.target_bars).copy()
            final_df.reset_index(drop=True, inplace=True)
            
            pq_path = os.path.join(self.output_dir, f"{self.symbol.upper()}_{tf}.parquet")
            csv_path = os.path.join(self.output_dir, f"{self.symbol.upper()}_{tf}.csv")
            
            final_df.to_parquet(pq_path)
            final_df.to_csv(csv_path, index=False)
            
            self.logger.info(f"Successfully bridged Timeframe {tf}m: {len(final_df)} bars stored perfectly.")

    def run(self, num_years=10):
        # 10 years of 1M data = ~3.5 million bars, enough for 55,000 bars at 4H resolution
        self._download_years(num_years)
        df = self._parse_and_merge()
        if not df.empty:
            self.resample_and_save(df)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    AltFetcher().run(num_years=10)
