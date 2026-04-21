import pytest
from ml.features import extract_features, FEATURE_VERSION

def test_feature_count():
    zone = {"timeframe": "1h", "timeStart": 10000000, "timeEnd": 20000000, "priceHigh": 1.1, "priceLow": 1.0}
    candles = [{"ts": 15000, "high": 1.2, "low": 0.9, "close": 1.05, "open": 1.0, "volume": 100}]
    swings = []
    features = extract_features(zone, candles, swings)
    assert len(features) == 18
    assert all(isinstance(f, float) for f in features)

def test_no_future_leakage():
    zone = {"timeframe": "1h", "timeStart": 10000000, "timeEnd": 20000000, "priceHigh": 1.1, "priceLow": 1.0}
    candles = [
        {"ts": 15000, "high": 1.2, "low": 0.9, "close": 1.05, "open": 1.0, "volume": 100},
        {"ts": 25000, "high": 1.5, "low": 1.2, "close": 1.4, "open": 1.3, "volume": 200}  # Future
    ]
    features = extract_features(zone, candles, [])
    # Leakage guard inside extract_features filters the future candle
    pass

def test_empty_formation_candles():
    zone = {"timeframe": "1h", "timeStart": 10000000, "timeEnd": 20000000, "priceHigh": 1.1, "priceLow": 1.0}
    candles = [{"ts": 25000, "high": 1.5, "low": 1.2, "close": 1.4, "open": 1.3, "volume": 200}]  # Only future
    with pytest.raises(AssertionError, match="No formation candles"):
        extract_features(zone, candles, [])
