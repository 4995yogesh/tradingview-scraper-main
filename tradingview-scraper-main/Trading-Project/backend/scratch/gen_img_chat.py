import os
import requests
import json
import sys

def generate_image_chat(prompt, filename):
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("ERROR: NVIDIA_API_KEY environment variable not set.")
        sys.exit(1)
        
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "stabilityai/stable-diffusion-3.5-large",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 1024
    }
    
    print(f"Calling NVIDIA API (chat endpoint) for model stabilityai/stable-diffusion-3.5-large...")
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.text}")
            return False
            
        res_data = response.json()
        content = res_data['choices'][0]['message']['content']
        
        print(f"Success! Content received (showing first 200 chars):")
        print(content[:200])
        
        # Save the content to a file to see what it is (might be base64 or a URL or text)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Content saved to {filename}")
        return True
    except Exception as e:
        print(f"Exception: {e}")
        return False

prompt = "A detailed technical blueprint diagram of a neural network model named 'Model C'. It shows input features (financial candle data) and an initial consolidation box on the left. In the center, it shows network layers processing the data. On the right, it shows the output: a refined consolidation box with tighter coordinates. Style: white lines on a dark blue blueprint background, schematic, precise, high-tech."

generate_image_chat(prompt, "variation1_chat_output.txt")
