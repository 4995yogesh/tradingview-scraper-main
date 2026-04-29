import os
import json
import requests
import time
from dotenv import load_dotenv

load_dotenv()

import subprocess
from pathlib import Path

class LLMManager:
    """
    Agentic Orchestrator for NVIDIA NIM models.
    Routes tasks to specialized models and chains results for maximum precision.
    """
    def __init__(self):
        self.api_key = os.environ.get("NVIDIA_API_KEY")
        self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.workspace_root = Path(__file__).parent.parent.parent
        
        # Specialist Registry
        self.REASONER = "nvidia/llama-3.1-nemotron-ultra-253b-v1"
        self.CODER = "meta/llama-3.3-70b-instruct"
        self.INTERPRETER = "nvidia/llama-3.1-nemotron-70b-instruct"

    def _run_graphify(self):
        """Regenerates the code map for fresh context."""
        try:
            print("DEBUG: [Graphify] Syncing code map...")
            script_path = self.workspace_root / "graphify_tmp.py"
            subprocess.run(["python", str(script_path)], cwd=self.workspace_root, capture_output=True)
        except Exception as e:
            print(f"DEBUG: [Graphify] Sync failed: {e}")

    def _get_code_context(self):
        """Reads the latest Graphify report."""
        report_path = self.workspace_root / "graphify-out" / "GRAPH_REPORT.md"
        if report_path.exists():
            return report_path.read_text(encoding="utf-8")
        return "No code context available."

    def _call(self, model, prompt, temp=0.5):
        if not self.api_key:
            return "ERROR: No NVIDIA_API_KEY"
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temp,
            "top_p": 0.7,
            "max_tokens": 1024
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload)
            if response.status_code != 200:
                return f"API Error ({response.status_code}): {response.text}"
            try:
                res = response.json()
                return res['choices'][0]['message']['content']
            except Exception as json_err:
                print(f"DEBUG: JSON Parse failed. Raw response: {response.text[:500]}")
                return f"JSON Error: {str(json_err)}"
        except Exception as e:
            return f"Model Error ({model}): {str(e)}"

    def execute_agentic_pipeline(self, sample):
        """
        Multi-step Agentic Workflow with Graphify Context:
        """
        # Always sync context first
        self._run_graphify()
        context = self._get_code_context()
        
        # Step 1: Deep Structural Reasoning
        reasoning_prompt = f"""
        CODE_CONTEXT:
        {context}
        
        TASK: Analyze this Consolidation Box refinement.
        SYMBOL: {sample.get('symbol')} | TF: {sample.get('timeframe')}
        ORIGINAL: {sample.get('original_meta')}
        USER_IDEAL: {sample.get('user_box')}
        OHLC_CONTEXT: {sample.get('ohlc_context')}
        
        Identify why the user adjusted the box and how it relates to the existing code structure.
        """
        print(f"DEBUG: Agent [Reasoner] starting analysis...")
        reasoning = self._call(self.REASONER, reasoning_prompt)
        
        # Step 2: Code Generation
        coding_prompt = f"""
        CODE_CONTEXT:
        {context}
        
        Based on reasoning: {reasoning}
        Provide precise Python logic for 'consolidation.py'.
        """
        print(f"DEBUG: Agent [Coder] generating logic...")
        logic = self._call(self.CODER, coding_prompt)
        
        # Step 3: Interpretation
        interpret_prompt = f"""
        Summarize the lesson learned.
        REASONING: {reasoning}
        LOGIC: {logic}
        """
        print(f"DEBUG: Agent [Interpreter] polishing result...")
        final_summary = self._call(self.INTERPRETER, interpret_prompt)
        
        return {
            "observation": final_summary,
            "suggested_logic": logic
        }

llm_manager = LLMManager()
