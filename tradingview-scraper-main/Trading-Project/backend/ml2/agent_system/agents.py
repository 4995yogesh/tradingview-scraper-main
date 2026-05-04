import json
import re

class TaskClassifier:
    @staticmethod
    def get_system_prompt():
        return """
        Analyze user input for Trading ML tasks.
        Output ONLY a JSON object with:
        {
          "task_type": "feature_engineering | model_debug | code_generation | pattern_analysis",
          "complexity": "low | medium | high",
          "latency_priority": boolean
        }
        """

    @staticmethod
    def parse_response(response):
        try:
            # Extract JSON if wrapped in code blocks
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(response)
        except:
            return {"task_type": "general_query", "complexity": "low", "latency_priority": True}

class PromptOptimizer:
    @staticmethod
    def optimize(task_data, raw_input):
        task_type = task_data.get("task_type")
        
        prompts = {
            "feature_engineering": f"Design a vectorized feature extraction function for OHLC data. Context: {raw_input}. Use NumPy/PyTorch. Ensure no future leakage.",
            "model_debug": f"Debug the following Trading ML model issue: {raw_input}. Analyze gradients, loss curves, and tensor shapes. Provide PyTorch fixes.",
            "pattern_analysis": f"Perform structural analysis on this price pattern: {raw_input}. Identify consolidation boundaries and volume profile anomalies.",
            "code_generation": f"Generate production-ready Python code for: {raw_input}. Requirements: docstrings, type hinting, and unit tests."
        }
        
        optimized = prompts.get(task_type, raw_input)
        
        return f"""
        ### TASK: {task_type.upper()}
        ### GOAL: {optimized}
        ### CONSTRAINTS: 
        - Use PyTorch/NumPy for ML logic.
        - No pseudocode.
        - Explain logic briefly.
        - Output structured code blocks.
        """

class OutputValidator:
    @staticmethod
    def validate(task_type, content):
        checks = {
            "code_generation": [r"def ", r"import ", r"class "],
            "feature_engineering": [r"np\.", r"torch\.", r"array"],
            "model_debug": [r"fix", r"cause", r"tensor"]
        }
        
        # Basic logical check for code presence
        required_patterns = checks.get(task_type, [])
        for pattern in required_patterns:
            if not re.search(pattern, content, re.IGNORECASE):
                return False, f"Missing required pattern: {pattern}"
                
        # Trading integrity check
        trading_keywords = ["price", "ohlc", "candle", "tensor", "model", "batch"]
        if not any(word in content.lower() for word in trading_keywords):
            return False, "Response lacks trading context."
            
        return True, "Validated"
