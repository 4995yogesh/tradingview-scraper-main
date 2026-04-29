import os
import json
import base64
import google.generativeai as genai
from training_db import training_db

# Load API Key
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

class GeminiTrainer:
    def __init__(self):
        self.model = genai.GenerativeModel('gemini-3.0-pro') # Use Pro for complex structural analysis

    def process_and_save(self, box_id):
        """Fetches a labeled box, sends to Gemini, and updates DB."""
        import sqlite3
        try:
            with sqlite3.connect("training_set.db") as conn:
                conn.row_factory = sqlite3.Row
                sample = conn.execute("SELECT * FROM review_queue WHERE box_id = ?", (box_id,)).fetchone()
                if not sample or not sample['user_box']:
                    return

            # Analyze via Gemini
            analysis_text = self.generate_refinement_report(dict(sample))
            
            # Extract only the observations/rules
            with sqlite3.connect("training_set.db") as conn:
                conn.execute(
                    "UPDATE review_queue SET gemini_analysis = ?, status = 'ANALYZED' WHERE box_id = ?",
                    (analysis_text, box_id)
                )
                conn.commit()
        except Exception as e:
            print(f"Gemini processing failed: {e}")

    def generate_refinement_report(self, sample):
        """
        Sends the OHLC data and metadata to Gemini for analysis.
        """
        prompt = f"""
        TASK: Refine a Trading Consolidation Detector.
        CONTEXT:
        - Symbol: {sample['symbol']}
        - Timeframe: {sample['timeframe']}
        - Detected Box (Rule-based): {sample['original_meta']}
        - Ideal Box (Human expert): {sample['user_box']}

        OHLC DATA CONTEXT (JSON):
        {sample['ohlc_context']}
        
        GOAL:
        1. Identify WHY the human expert shifted the boundaries compared to the Rule-based box. Look closely at the OHLC Data (candles) around the timeStart and timeEnd boundaries of both boxes.
        2. Extract features (e.g., "The user included a failed breakout wick", "The user started the box after a specific volume spike", "The user tightened the price High/Low to exclude noise").
        3. Propose a modification to the Python logic in 'consolidation.py' to achieve this refinement automatically.

        Format your response as JSON:
        {{
          "observation": "...",
          "key_features": ["...", "..."],
          "logic_adjustment": "Python code snippet or logical rule"
        }}
        """

        response = self.model.generate_content([prompt])
        return response.text

gemini_trainer = GeminiTrainer()
