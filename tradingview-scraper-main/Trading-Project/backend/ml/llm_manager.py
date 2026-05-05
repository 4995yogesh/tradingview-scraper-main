import os
import json
import requests
import time
import threading
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
        # ROOT is 3 levels up from Trading-Project/backend/ml/llm_manager.py
        # backend/ml/llm_manager.py -> backend/ml -> backend -> Trading-Project -> ROOT
        self.workspace_root = Path(__file__).parent.parent.parent.parent
        self._last_sync = 0
        self._sync_lock = threading.Lock()
        self._last_request_time = 0
        self._rate_limit_lock = threading.Lock()

        # Specialist Registry (Valid NVIDIA NIM model names)
        self.REASONER = "nvidia/llama-3.1-nemotron-70b-instruct"
        self.CODER = "meta/llama-3.3-70b-instruct"
        self.INTERPRETER = "meta/llama-3.3-70b-instruct"
        
    def _enforce_rate_limit(self):
        """Ensures max 40 requests per minute (1.55s per request) globally."""
        with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < 1.55:
                time.sleep(1.55 - elapsed)
            self._last_request_time = time.time()

    def _run_graphify(self):
        """Regenerates the code map periodically for fresh context."""
        with self._sync_lock:
            now = time.time()
            if now - self._last_sync < 900: # 15 minute cache
                return
                
            try:
                print("DEBUG: [Graphify] Syncing code map (Cache expired)...")
                script_path = self.workspace_root / "graphify_tmp.py"
                subprocess.run(["python", str(script_path)], cwd=self.workspace_root, capture_output=True)
                self._last_sync = time.time()
            except Exception as e:
                print(f"DEBUG: [Graphify] Sync failed: {e}")

    def _get_code_context(self):
        """Reads the latest Graphify report."""
        report_path = self.workspace_root / "tradingview-scraper-main" / "graphify-out" / "GRAPH_REPORT.md"
        if not report_path.exists():
            # Fallback for alternative structure
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
        
        max_retries = 4
        for attempt in range(max_retries):
            self._enforce_rate_limit()
            try:
                response = requests.post(self.base_url, headers=headers, json=payload)
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
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
        
        return "API Error (429): {'status':429, 'title':'Too Many Requests'}"

    def execute_agentic_pipeline(self, sample):
        """
        Multi-step Agentic Workflow with Graphify Context:
        """
        # Always sync context first
        self._run_graphify()
        context = self._get_code_context()
        
        # Format user_box — always a list now; render each box clearly
        try:
            import json as _json
            raw_ub = sample.get('user_box')
            ub_parsed = _json.loads(raw_ub) if isinstance(raw_ub, str) else raw_ub
            if isinstance(ub_parsed, dict):
                ub_parsed = [ub_parsed]
            ub_lines = "\n".join(
                f"  Box {i+1}: start={b.get('timeStart')} end={b.get('timeEnd')} high={b.get('priceHigh')} low={b.get('priceLow')}"
                for i, b in enumerate(ub_parsed or [])
            )
        except Exception:
            ub_lines = str(sample.get('user_box'))

        reasoning_prompt = f"""
        TASK: Analyze the Consolidation Box refinement and explain the trading logic behind the user's adjustments.
        SYMBOL: {sample.get('symbol')} | TF: {sample.get('timeframe')}
        ORIGINAL BOX: {sample.get('original_meta')}
        USER-ADJUSTED BOX(ES):\n{ub_lines}
        OHLC CONTEXT: {sample.get('ohlc_context')}

        Please provide a plain-English explanation of the price action, wicks, and candle closes that led to the user's adjustments. Focus on the chart observations and trading logic. Respond in simple bullet points, avoiding any technical or programming-related terms.
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
