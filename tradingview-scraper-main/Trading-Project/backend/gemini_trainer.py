import os
import time
import requests
import json
import base64
from training_db import training_db
from dotenv import load_dotenv

load_dotenv()
NV_API_KEY = os.environ.get("NVIDIA_API_KEY")
NV_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct" # Standard NIM name, will fallback to your 253B if specified

from ml.llm_manager import llm_manager

class GeminiTrainer: # Orchestrator wrapper
    def __init__(self):
        pass

    def process_and_save(self, box_id):
        """Runs the Multi-Agent pipeline and updates DB."""
        import sqlite3
        try:
            print(f"DEBUG: Starting Multi-Agent Analysis for {box_id}")
            with sqlite3.connect("training_set.db") as conn:
                conn.row_factory = sqlite3.Row
                sample = conn.execute("SELECT * FROM review_queue WHERE box_id = ?", (box_id,)).fetchone()
                
                if not sample or not sample['user_box']:
                    return

            # Execute Agentic Pipeline
            result = llm_manager.execute_agentic_pipeline(dict(sample))
            
            # Store the final summary as the main analysis
            combined_text = f"{result['observation']}\n\n---\nLOGIC: {result['suggested_logic']}"
            
            with sqlite3.connect("training_set.db") as conn:
                conn.execute(
                    "UPDATE review_queue SET gemini_analysis = ?, status = 'ANALYZED' WHERE box_id = ?",
                    (combined_text, box_id)
                )
                conn.commit()
            print(f"DEBUG: Successfully ANALYZED {box_id} via Multi-Agent Chain")
        except Exception as e:
            print(f"DEBUG: Agentic pipeline failed for {box_id}: {e}")


    def reprocess_missing_analyses(self):
        """Finds LABELED/ANALYZED-with-error boxes and processes them sequentially (rate-limit safe)."""
        import sqlite3
        try:
            with sqlite3.connect("training_set.db") as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT box_id FROM review_queue 
                    WHERE status = 'LABELED'
                    OR (status = 'ANALYZED' AND (
                        gemini_analysis LIKE '%API Error%'
                        OR gemini_analysis LIKE '%429%'
                        OR gemini_analysis IS NULL
                    ))
                    ORDER BY created_at DESC
                    LIMIT 50
                """).fetchall()

            print(f"DEBUG: Found {len(rows)} boxes to analyze. Processing sequentially (rate-limit safe)...")
            for r in rows:
                self.process_and_save(r['box_id'])
                time.sleep(2.0)  # ~30 RPM — well within 40 RPM budget

        except Exception as e:
            print(f"DEBUG: Reprocess failed: {e}")


gemini_trainer = GeminiTrainer()
# Auto-reprocess on startup to catch up
import threading
threading.Thread(target=gemini_trainer.reprocess_missing_analyses, daemon=True).start()
