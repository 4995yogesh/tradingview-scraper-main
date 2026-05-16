import os
import requests
import base64
import sys

def generate_image_qwen(prompt, filename, endpoint="images/generations"):
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("ERROR: NVIDIA_API_KEY environment variable not set.")
        sys.exit(1)
        
    url = f"https://integrate.api.nvidia.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    if endpoint == "images/generations":
        payload = {
            "model": "qwen-image",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json"
        }
    else: # chat/completions
        payload = {
            "model": "qwen-image",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "max_tokens": 1024
        }
        
    print(f"Calling NVIDIA API ({endpoint}) for model qwen-image...")
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.text}")
            return False
            
        res_data = response.json()
        
        if endpoint == "images/generations":
            img_b64 = res_data['data'][0]['b64_json']
            with open(filename, "wb") as f:
                f.write(base64.b64decode(img_b64))
            print(f"Image saved to {filename}")
        else:
            content = res_data['choices'][0]['message']['content']
            print(f"Content received from chat endpoint:")
            print(content[:200])
            with open(filename + ".txt", "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Content saved to {filename}.txt")
            
        return True
    except Exception as e:
        print(f"Exception: {e}")
        return False

prompt = "A detailed technical blueprint diagram of a neural network model named 'Model C'. It shows input features (financial candle data) and an initial consolidation box on the left. In the center, it shows network layers processing the data. On the right, it shows the output: a refined consolidation box with tighter coordinates. Style: white lines on a dark blue blueprint background, schematic, precise, high-tech."

print("Trying images/generations endpoint...")
if not generate_image_qwen(prompt, "qwen_blueprint.png", "images/generations"):
    print("\nTrying chat/completions endpoint as fallback...")
    generate_image_qwen(prompt, "qwen_blueprint", "chat/completions")
