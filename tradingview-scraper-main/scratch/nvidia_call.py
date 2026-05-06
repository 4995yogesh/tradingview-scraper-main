import requests
import json
import sys

def call_nvidia(prompt, model="meta/llama-3.1-405b-instruct"):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer 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",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "top_p": 0.7,
        "max_tokens": 1024
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content']
    else:
        return f"Error: {response.status_code} - {response.text}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python nvidia_call.py '<prompt>'")
        sys.exit(1)
    
    prompt = sys.argv[1]
    result = call_nvidia(prompt)
    print(result)
