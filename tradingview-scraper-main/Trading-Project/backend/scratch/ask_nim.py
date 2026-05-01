import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.llm_manager import llm_manager

prompt = '''
File: `project/indicators/consolidation.py`

We want to integrate the newly trained PyTorch model (`backend/models/consolidation_nn.pt`) into the `consolidation_boxes` function (or a helper class it uses).

Requirements:
1. Loading: Attempt to load `backend/models/consolidation_nn.pt` using PyTorch. 
   - Define the `ConsolidationCNN` architecture (must match `ml/train_nn.py`).
   - If model file exists, load state_dict.
2. Inference:
   - In `consolidation_boxes`, after computing heuristic zones, or instead of them (user preference: "use the best once", but usually we want to refine/score them).
   - Actually, let's make it a hybrid:
     - Keep heuristic detection (it's fast and finds candidates).
     - For each heuristic candidate, use the NN to "refine" the bounding box or "score" it.
     - IF the user said "use the api models" for the training, they might mean replacing the logic.
   - RE-READ user request: "then generate boxes on the main chart by fixing the consolidation.py".
   - Okay, let's use the NN to detect zones directly if available.

3. NN Detection Logic:
   - Take the last 100 candles.
   - Normalize.
   - Run model.
   - Output [start, end, high, low].
   - Map back to price/time.

Return ONLY the code to add/modify `project/indicators/consolidation.py` to support this.
'''

print(llm_manager._call(llm_manager.CODER, prompt))
