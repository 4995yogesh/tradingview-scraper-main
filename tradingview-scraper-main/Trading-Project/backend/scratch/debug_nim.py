import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")
base_url = "https://integrate.api.nvidia.com/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": "nvidia/llama-3.1-nemotron-70b-instruct",
    "messages": [{"role": "user", "content": "Hello"}],
    "temperature": 0.5,
    "top_p": 0.7,
    "max_tokens": 10
}

response = requests.post(base_url, headers=headers, json=payload)
print(response.text)
