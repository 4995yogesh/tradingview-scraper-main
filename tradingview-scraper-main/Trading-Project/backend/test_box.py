import sqlite3
import json
import sys
sys.path.insert(0, 'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend')
from ml.nn_scorer import predict_box, load_nn_model

conn = sqlite3.connect('C:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/data/training_set.db')
c = conn.cursor()
c.execute('SELECT ohlc_context FROM review_queue WHERE box_id="0769c7eda49d4493"')
row = c.fetchone()
conn.close()

if row:
    load_nn_model()
    print("OUTPUT:", predict_box(json.loads(row[0])))
else:
    print("BOX NOT FOUND")
