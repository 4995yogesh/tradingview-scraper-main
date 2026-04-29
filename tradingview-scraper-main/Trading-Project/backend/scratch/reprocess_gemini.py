import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

try:
    from gemini_trainer import gemini_trainer
    print("DEBUG: Importer success")
    gemini_trainer.reprocess_missing_analyses()
except Exception as e:
    print(f"CRITICAL ERROR: {e}")
