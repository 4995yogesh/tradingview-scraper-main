"""
ml/llm_translator.py — Gemini LLM translator layer.

Reads user comments on consolidation boxes and extracts
normalized numeric signals to augment ML features.
Runs asynchronously — never blocks label saving.
"""

import os
import json
import logging
import threading

logger = logging.getLogger(__name__)

# ── LLM feature names appended after base v1 features ────────────────────────
LLM_FEATURE_NAMES = [
    "llm_trend_alignment",      # -1=against trend, 0=neutral, 1=with trend
    "llm_range_tightness",      # 0-1: how tight/clean the range was
    "llm_breakout_strength",    # 0-1: strength of breakout mentioned
    "llm_volume_quality",       # 0-1: volume behavior quality
    "llm_structure_quality",    # 0-1: overall structure quality
    "llm_sentiment_score",      # -1=very bad, 0=neutral, 1=very good
]

_PROMPT_TEMPLATE = """
You are a professional forex trader assistant. A user has labeled a price consolidation box and left a comment explaining their reasoning.

Box rating: {label}

User comment: "{comment}"

Your job is to extract 6 numeric trading signals from the comment.
Return ONLY a valid JSON object with these exact keys and values between -1.0 and 1.0:

{{
  "llm_trend_alignment": <-1 to 1, negative=against trend, positive=with trend>,
  "llm_range_tightness": <0 to 1, higher=tighter/cleaner range>,
  "llm_breakout_strength": <0 to 1, higher=stronger breakout>,
  "llm_volume_quality": <0 to 1, higher=better volume behavior>,
  "llm_structure_quality": <0 to 1, overall market structure quality>,
  "llm_sentiment_score": <-1 to 1, negative=bad box, positive=good box>
}}

Rules:
- Only output the JSON. No explanation, no markdown.
- If the comment gives no info for a field, use 0.0
- Infer from context (e.g. "tight range" means high range_tightness)
"""

# ── Neutral fallback (no API / no comment) ────────────────────────────────────
NEUTRAL_LLM_FEATURES = [0.0] * len(LLM_FEATURE_NAMES)

_client = None
_lock   = threading.Lock()

def _get_client():
    """Lazy init of Gemini client."""
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("[llm_translator] GEMINI_API_KEY not set — LLM features disabled")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _client = genai.GenerativeModel("gemini-3.1-pro")
        logger.info("[llm_translator] Gemini client initialized (gemini-3.1-pro)")
        return _client
    except Exception as exc:
        logger.error("[llm_translator] Failed to init Gemini: %s", exc)
        return None


def extract_llm_features(comment: str, label: str) -> list:
    """
    Call Gemini to translate a user comment into numeric features.
    Returns list of 6 floats. Falls back to NEUTRAL_LLM_FEATURES on error.
    """
    if not comment or not comment.strip():
        return NEUTRAL_LLM_FEATURES

    client = _get_client()
    if client is None:
        return NEUTRAL_LLM_FEATURES

    prompt = _PROMPT_TEMPLATE.format(label=label, comment=comment.strip())
    try:
        response = client.generate_content(prompt)
        raw = response.text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        features = [
            float(_clamp(data.get("llm_trend_alignment", 0.0),    -1.0, 1.0)),
            float(_clamp(data.get("llm_range_tightness", 0.0),     0.0, 1.0)),
            float(_clamp(data.get("llm_breakout_strength", 0.0),   0.0, 1.0)),
            float(_clamp(data.get("llm_volume_quality", 0.0),      0.0, 1.0)),
            float(_clamp(data.get("llm_structure_quality", 0.0),   0.0, 1.0)),
            float(_clamp(data.get("llm_sentiment_score", 0.0),    -1.0, 1.0)),
        ]
        logger.info("[llm_translator] Extracted: %s", dict(zip(LLM_FEATURE_NAMES, features)))
        return features

    except Exception as exc:
        logger.warning("[llm_translator] Gemini extraction failed: %s", exc)
        return NEUTRAL_LLM_FEATURES


def _clamp(val, lo, hi):
    try:
        return max(lo, min(hi, float(val)))
    except Exception:
        return 0.0


def append_llm_to_vector(base_vec: list, comment: str, label: str) -> list:
    """
    Append LLM-extracted features to an existing base feature vector.
    Returns base_vec + 6 LLM floats = 24 total features.
    """
    llm_feats = extract_llm_features(comment, label)
    return list(base_vec) + llm_feats
