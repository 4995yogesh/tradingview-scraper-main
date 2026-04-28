import logging
from ml import db as ml_db
from ml.quality.features import extract_quality_features
from ml.quality.db import save_quality_sample, init_db as quality_init_db, get_conn
from pipeline.data.db import candle_db

logger = logging.getLogger(__name__)

LABEL_MAP = {
    "very_good": 0.875,
    "good": 0.625,
    "bad": 0.375,
    "very_bad": 0.125
}

def build_quality_dataset():
    """
    Scrape labels from existing ML DB, extract new features, and store in quality DB.
    """
    quality_init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM quality_store")
        
    labels = ml_db.get_all_labels()
    logger.info(f"[quality.data] Found {len(labels)} total labels in primary DB")
    
    count = 0
    for l in labels:
        box_id = l['box_id']
        symbol = l.get('symbol', 'EURUSD')
        tf = l.get('timeframe', '1h')
        t_start = l['time_start_ms'] // 1000
        t_end = l['time_end_ms'] // 1000
        
        # Fetch candles for this box
        candles = candle_db.get_candles(
            exchange=l.get('exchange', 'OANDA'),
            symbol=symbol,
            timeframe=tf,
            start_ts=t_start,
            end_ts=t_end
        )
        
        if not candles:
            logger.warning(f"[quality.data] No candles for {box_id}")
            continue
            
        score = LABEL_MAP.get(l['label'], 0.5)
        features = extract_quality_features(candles, l['price_high'], l['price_low'])
        
        save_quality_sample(box_id, features, score)
        count += 1
        
    logger.info(f"[quality.data] Successfully processed {count} samples")
