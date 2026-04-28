import json
import re
import logging

logger = logging.getLogger(__name__)

def build_prompt(features):
    return f"""
You are an expert Forex Trading Pattern Analyst specializing in Price Action and Market Structure.
Your goal is to interpret structural features of a consolidation box and provide reasoning.

DATA FEATURES:
{json.dumps(features, indent=2)}

GUIDELINES:
- A "GOOD" structure is balanced, shows clear boundary rejection, and has low internal noise.
- A "BAD" structure shows directional pressure (drifting), weak boundary respect, or highly erratic behavior.
- Use 'behavior_score' and 'movement_efficiency' as primary structure indicators.

YOU MUST return a STRICT JSON object in this format:
{{
  "interpretation": "Detailed 1-sentence analytical reasoning.",
  "structure_type": "balanced" | "drifting" | "unclear",
  "confidence": <float 0.0 to 1.0>
}}
"""

class MockGeminiClient:
    def generate_content(self, prompt):
        import json
        class Resp:
            def __init__(self):
                self.text = json.dumps({
                    "interpretation": "Structure shows balanced behavior with clear rejection.",
                    "structure_type": "balanced",
                    "confidence": 0.85
                })
        return Resp()

def gemini_label(features, gemini_client):
    """
    Controlled reasoning wrapper.
    """
    if gemini_client is None:
        gemini_client = MockGeminiClient()
        
    prompt = build_prompt(features)
    
    try:
        # Assuming gemini_client has generate_content method
        response = gemini_client.generate_content(prompt)
        text = response.text
        
        # Safe Parse JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return parsed
        else:
            raise ValueError("No JSON found in response")
            
    except Exception as e:
        logger.error(f"Gemini API Error: {str(e)}")
        return {
            "interpretation": "API Error or Malformed response",
            "structure_type": "unclear",
            "confidence": 0.0
        }
