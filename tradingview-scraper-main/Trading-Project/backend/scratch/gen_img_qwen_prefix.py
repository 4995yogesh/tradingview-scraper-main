import os
import requests
import base64
import sys

def generate_image_qwen(prompt, filename, model_name):
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("ERROR: NVIDIA_API_KEY environment variable not set.")
        sys.exit(1)
        
    url = "https://integrate.api.nvidia.com/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json"
    }
    
    print(f"Calling NVIDIA API for model {model_name}...")
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.text}")
            return False
            
        res_data = response.json()
        img_b64 = res_data['data'][0]['b64_json']
        
        with open(filename, "wb") as f:
            f.write(base64.b64decode(img_b64))
        print(f"Image saved to {filename}")
        return True
    except Exception as e:
        print(f"Exception: {e}")
        return False

prompt = "A detailed technical blueprint diagram of a neural network model named 'Model C'. It shows input features (financial candle data) and an initial consolidation box on the left. In the center, it shows network layers processing the data. On the right, it shows the output: a refined consolidation box with tighter coordinates. Style: white lines on a dark blue blueprint background, schematic, precise, high-tech."

models = ["nvidia/qwen-image", "qwen/qwen-image"]

for model in models:
    print(f"\nTrying {model}...")
    if generate_image_qwen(prompt, f"qwen_{model.replace('/', '_')}.png", model):
        break
