import sys
import os
import pandas as pd
import numpy as np

# Add project root and backend to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "backend"))

from project.indicators.user_style_learner import UserStyleLearner
from project.indicators.adaptive_consolidation import adaptive_consolidation_boxes

def test_evolution_and_generation():
    print("Starting Rule Evolution Test...")
    
    # Use a test database
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_rule_evolution.db"))
    if os.path.exists(db_path):
        os.remove(db_path)
        
    learner = UserStyleLearner(db_path=db_path)
    
    # Check initial params
    params = learner.get_parameters()
    print("Initial touch_thresh_pct:", params.get('touch_thresh_pct'))
    assert params.get('touch_thresh_pct') == 0.05
    
    # Create mock OHLC data
    dates = pd.date_range(start="2026-01-01", periods=100, freq="1h")
    df = pd.DataFrame({
        'open': np.random.randn(100) + 100,
        'high': np.random.randn(100) + 102,
        'low': np.random.randn(100) + 98,
        'close': np.random.randn(100) + 100
    }, index=dates)
    
    # Simulate feedback to trigger evolution
    orig = {"start": 10, "end": 20, "top": 105.0, "bottom": 95.0, "type": "LOOSE", "score": 1.0}
    user = {"start": 10, "end": 20, "top": 107.0, "bottom": 95.0} # User included a top wick
    
    # Record 3 edits to trigger pattern-based evolution (threshold=3)
    learner.record_feedback("TEST", "1h", orig, user, "edited")
    learner.record_feedback("TEST", "1h", orig, user, "edited")
    learner.record_feedback("TEST", "1h", orig, user, "edited")
    
    # Check if evolved
    params_after = learner.get_parameters()
    print("Evolved touch_thresh_pct:", params_after.get('touch_thresh_pct'))
    assert params_after.get('touch_thresh_pct') > 0.05
    
    # Test generation
    try:
        boxes = adaptive_consolidation_boxes(df, min_bars=5)
        print(f"Generated {len(boxes)} boxes successfully.")
        print("Test PASSED.")
    except Exception as e:
        print(f"Generation failed: {e}")
        print("Test FAILED.")
        
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == '__main__':
    test_evolution_and_generation()
