import sys
import os

# Mock the path setup from server.py
PIPE = os.path.abspath(os.path.join(os.getcwd(), "Trading-Project", "backend"))
PROJECT = os.path.abspath(os.path.join(os.getcwd(), "Trading-Project", "project"))
sys.path.insert(0, PIPE)
sys.path.insert(0, PROJECT)

try:
    from ml.shared_models import ConsolidationCNN
    model = ConsolidationCNN(sequence_length=100)
    print("SUCCESS: ConsolidationCNN initialized from ml.shared_models")
    
    from indicators.consolidation import NNPredictor
    print("SUCCESS: NNPredictor imported from indicators.consolidation")
    
except Exception as e:
    print(f"FAILURE: {e}")
    import traceback
    traceback.print_exc()
