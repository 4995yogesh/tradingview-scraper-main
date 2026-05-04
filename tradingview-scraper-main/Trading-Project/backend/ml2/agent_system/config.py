import os

# NVIDIA API Credentials
NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Model Registry
MODEL_REGISTRY = {
    "reasoning": "meta/llama-3.1-405b-instruct",
    "code":      "meta/llama-3.1-70b-instruct",
    "analysis":  "nvidia/llama-3.1-nemotron-70b-instruct",
    "fast":      "meta/llama-3.1-8b-instruct"
}

# Task Mapping
TASK_TO_MODEL = {
    "feature_engineering": "code",
    "model_debug":         "reasoning",
    "pattern_analysis":    "analysis",
    "code_generation":     "code",
    "general_query":       "fast"
}

# Persistence
FEEDBACK_LOG = "feedback_loop.json"
