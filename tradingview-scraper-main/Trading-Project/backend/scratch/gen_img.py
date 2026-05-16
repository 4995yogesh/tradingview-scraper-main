import os
import requests
import base64
import sys

def generate_image(prompt, filename, model="nvidia/flux-1-dev"):
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
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json"
    }
    
    print(f"Calling NVIDIA API for model {model}...")
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

# Prompts
prompts = {
    "variation1.png": "A detailed technical blueprint diagram of a neural network model named 'Model C'. It shows input features (financial candle data) and an initial consolidation box on the left. In the center, it shows network layers processing the data. On the right, it shows the output: a refined consolidation box with tighter coordinates. Style: white lines on a dark blue blueprint background, schematic, precise, high-tech.",
    "variation2.png": "An artistic abstract representation of data flowing through a neural network. Glowing streams of financial data (candlesticks) enter a central glowing node or mesh. The output is a perfectly framed glowing rectangle representing a refined trading zone. Style: dark mode, neon glow, cybernetic, abstract, vibrant colors.",
    "variation3.png": "A mockup of a professional trading dashboard interface named 'Refine Studio'. It shows a candlestick chart with a rough initial box and a smaller, tighter green box labeled 'NN Refined' overlaid. On the side panel, a simple diagram shows the neural network layers connecting input to output. Style: modern UI, dark mode, professional trading platform aesthetic, clean."
}

# Try with flux-1-dev first
success = True
for filename, prompt in prompts.items():
    print(f"\nGenerating {filename}...")
    if not generate_image(prompt, filename, "nvidia/flux-1-dev"):
        print("Trying fallback model stabilityai/sdxl...")
        if not generate_image(prompt, filename, "stabilityai/sdxl"):
            print(f"Failed to generate {filename}")
            success = False

if success:
    print("\nAll images generated successfully.")
else:
    print("\nSome images failed to generate.")
