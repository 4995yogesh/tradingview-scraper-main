import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.llm_manager import llm_manager
print(llm_manager._call(llm_manager.CODER, "Return exactly the word 'DONE' and nothing else."))
