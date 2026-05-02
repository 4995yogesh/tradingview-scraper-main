import traceback
import sys
sys.path.insert(0, 'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend')
from ml.nn_scorer import load_nn_model

try:
    load_nn_model()
    print('SUCCESS')
except Exception as e:
    print('ERROR:')
    traceback.print_exc()
