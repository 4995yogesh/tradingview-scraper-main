import sys
import os
import json

# Path setup
sys.path.append(os.path.join(os.getcwd(), "Trading-Project", "backend"))

from ml.quality.autolabel.auto_labeller import auto_label_pipeline

# 1. Mock Gemini Client (Example Wrapper)
class MockGeminiClient:
    def generate_content(self, prompt):
        # In real life, this would call google.generativeai
        # and prompt would contain instructions for JSON format.
        class Response:
            def __init__(self):
                self.text = json.dumps({
                    "interpretation": "Tight range with strong rejection at high boundary, suggests balanced consolidation.",
                    "structure_type": "balanced",
                    "confidence": 0.85
                })
        return Response()

# 2. Mock Extractor
class MockExtractor:
    def extract(self, box):
        # Returns a mock of the 23 features built previously
        return {
            "behavior_score": 0.45,
            "wick_ratio": 1.8,
            "movement_efficiency": 0.75,
            "respect_score": 0.92,
            "structure_penalty": 0.05,
            "log_duration": 2.5
        }

# 3. Example Run
if __name__ == "__main__":
    boxes = [
        {"box_id": "test_1", "start": 1777000000, "end": 1777003600, "symbol": "EURUSD"}
    ]
    
    gemini = MockGeminiClient()
    extractor = MockExtractor()
    
    print("--- Running Hybrid Auto-Labeller Pipeline ---")
    results = auto_label_pipeline(boxes, extractor, gemini)
    
    for r in results:
        print(f"\nBox ID: {r['box_id']}")
        print(f"  Final Label: {r['label']}")
        print(f"  Confidence:  {r['confidence']}")
        print(f"  Status:      {r['status']}")
        print(f"  Approved:    {r['approved']}")
        print(f"  Reason:      {r['reason']}")
