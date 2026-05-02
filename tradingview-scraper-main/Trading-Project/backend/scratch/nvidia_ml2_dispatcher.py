import os
import requests
import json
import sys

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

def ask_nvidia(prompt):
    invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "meta/llama-3.1-70b-instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "top_p": 0.7,
        "max_tokens": 4096,
    }
    print(f"Requesting NVIDIA API with model: {payload['model']}...")
    response = requests.post(invoke_url, headers=headers, json=payload)
    print(f"Response status: {response.status_code}")
    res_json = response.json()
    if 'choices' not in res_json:
        print(f"Error in API response: {res_json}")
        return ""
    return res_json['choices'][0]['message']['content']

def generate_train_c():
    prompt = """
    Create a PyTorch training script 'train_c.py' for Model C (Refinement).
    - Model C takes (features, initial_box) as input.
    - initial_box is a tensor [batch, 2] (start_idx, end_idx).
    - Target is the ground truth box from the dataset (seg_mask edges).
    - Use ConsolidationDataset from dataset.py.
    - Model C is defined in model_c.py.
    - Save model to data/models/model_c.pt.
    - Handle relative paths correctly.
    """
    code = ask_nvidia(prompt)
    return code

def generate_train_d():
    prompt = """
    Create a PyTorch training script 'train_d.py' for Model D (Quality Scorer).
    - Model D takes (features, box) as input.
    - Target is batch['quality_score'].
    - Use ConsolidationDataset from dataset.py.
    - Model D is defined in model_d.py.
    - Save model to data/models/model_d.pt.
    """
    code = ask_nvidia(prompt)
    return code

if __name__ == "__main__":
    if not NVIDIA_API_KEY:
        print("Error: NVIDIA_API_KEY not set.")
        sys.exit(1)
    
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if target in ["train_c", "all"]:
        print("Generating train_c.py...")
        code = generate_train_c()
        with open("ml2/train_c.py", "w") as f:
            f.write(code)
            
    if target in ["train_d", "all"]:
        print("Generating train_d.py...")
        code = generate_train_d()
        with open("ml2/train_d.py", "w") as f:
            f.write(code)
