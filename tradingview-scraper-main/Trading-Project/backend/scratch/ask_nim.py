import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.llm_manager import llm_manager

prompt = '''
File: `project/indicators/consolidation.py`

Current termination logic:
```python
if c > rangeTop or c < rangeBottom or isBlockedTime:
    activeBox["end"] = i - 1
    ...
```

New Requirement:
"If a candle closes solid outside of a box and the candle preceeding it has a wick at the box boundary, the box should terminate at the wicking candle."

Interpretation:
1. Current candle `i` closes outside (`c > rangeTop` or `c < rangeBottom`).
2. Preceding candle `i-1` has a wick at the boundary (`h1 >= rangeTop * 0.999` or `l1 <= rangeBottom * 1.001` or similar "touch" logic).
3. If both true, terminate at `i-1`. (Note: `i-1` is already the termination point in the current code).

Wait, if the user is asking for this, maybe the current code is terminating at `i`?
No, line 73 says `activeBox["end"] = i - 1`.

Maybe the user wants to ENSURE it terminates at `i-1` ONLY IF it wicks, otherwise maybe it terminates at `i`?
No, "closes solid outside" usually means the box is over.

Actually, let's look at the "expansion" logic:
```python
89:                 if age <= 5:
90:                     if h > rangeTop:    rangeTop    = h
91:                     if l < rangeBottom: rangeBottom = l
```
The box expands in the first 5 candles.
If it breaks out at candle 7, it ends at 6.

Maybe the user wants to adjust the logic so that if it breaks out at `i`, we check if `i-1` was a "test".
If `i-1` was NOT a test, maybe we should have terminated earlier? Unlikely.

Let's assume the user wants a stricter "wick touch" requirement for the termination candle to be considered the "edge".
Actually, I'll just refine the termination to be more explicit about this rule.

Provide the code change for `consolidation.py`.
'''

print(llm_manager._call(llm_manager.CODER, prompt))
