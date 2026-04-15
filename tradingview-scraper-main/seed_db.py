import sys
import pandas as pd

sys.path.insert(0, './Trading-Project')
from pipeline.data.db import candle_db

tf_map = {'1': '1m', '5': '5m', '15': '15m', '60': '1h', '240': '4h'}

def seed_db():
    for tf_num, tf_db in tf_map.items():
        csv_path = f'./ohlc_data_pro/EURUSD_{tf_num}.csv'
        try:
            print(f"Reading {csv_path}...")
            df = pd.read_csv(csv_path)
            records = df.to_dict('records')
            for r in records:
                r['timestamp'] = r['ts']
            
            print(f"Upserting {len(records)} bars to DB for {tf_db}...")
            candle_db.upsert_candles('OANDA', 'EURUSD', tf_db, records)
            candle_db.log_refresh('OANDA', 'EURUSD', tf_db, int(df['ts'].max()))
            print(f'Done migrating {tf_db}.\n')
        except FileNotFoundError:
            print(f"File {csv_path} not found. Skipping.")
        except Exception as e:
            print(f'Error on {tf_db}: {e}')

if __name__ == '__main__':
    seed_db()
