import json
import os
import requests
from .config import NVIDIA_API_KEY, NVIDIA_BASE_URL, MODEL_REGISTRY, TASK_TO_MODEL, FEEDBACK_LOG

class RufloRouter:
    def __init__(self):
        self.api_key = NVIDIA_API_KEY
        self.base_url = NVIDIA_BASE_URL
        self.history = self._load_history()

    def _load_history(self):
        if os.path.exists(FEEDBACK_LOG):
            with open(FEEDBACK_LOG, 'r') as f:
                return json.load(f)
        return []

    def _save_history(self, entry):
        self.history.append(entry)
        with open(FEEDBACK_LOG, 'w') as f:
            json.dump(self.history, f, indent=2)

    def select_model(self, task_type, complexity, latency_priority):
        """
        Logic for selecting the best NVIDIA model via Ruflo Controller logic.
        """
        # Complexity Override
        if complexity == "high":
            return MODEL_REGISTRY["reasoning"]
        
        # Latency Priority
        if latency_priority:
            return MODEL_REGISTRY["fast"]

        # Default Task-based mapping
        model_key = TASK_TO_MODEL.get(task_type, "fast")
        return MODEL_REGISTRY[model_key]

    def execute(self, model_name, prompt, system_prompt="You are a helpful assistant."):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 4096
        }

        try:
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            # Log success
            self._save_history({
                "model": model_name,
                "task_type": "unknown", # To be filled by main flow
                "status": "success"
            })
            
            return content
        except Exception as e:
            # Fallback Logic
            fallback = MODEL_REGISTRY["fast"]
            print(f"Error with {model_name}, falling back to {fallback}: {e}")
            return self.execute(fallback, prompt, system_prompt)

    def log_feedback(self, task_type, model_used, score):
        self._save_history({
            "task_type": task_type,
            "model_used": model_used,
            "success_score": score
        })
