import requests
import os

NVIDIA_API_KEY = "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"

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {NVIDIA_API_KEY}",
    "Content-Type": "application/json",
}
payload = {
    "model": "meta/llama-3.1-70b-instruct",
    "messages": [{"role": "user", "content": "Hello, world!"}],
    "temperature": 0.2,
    "top_p": 0.7,
    "max_tokens": 1024,
}
try:
    print("Testing connection...")
    response = requests.post(invoke_url, headers=headers, json=payload, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
