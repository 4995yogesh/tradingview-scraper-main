import sys
sys.path.append('./backend')
from backend.ml import trainer
import traceback

try:
    trainer._run_training(force=True)
    print('success')
except Exception as e:
    print('FAILURE', e)
    traceback.print_exc()
