import torch
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_path = os.path.join(backend_dir, 'Trading-Project', 'backend', 'data', 'models', 'model_a.pt')

if os.path.exists(model_path):
    print(f"Loading model from: {model_path}")
    state_dict = torch.load(model_path, map_location='cpu')
    if 'g1.conv.weight' in state_dict:
        print(f"g1.conv.weight shape: {state_dict['g1.conv.weight'].shape}")
    else:
        print("g1.conv.weight not found in state_dict")
        print("Keys:", state_dict.keys())
else:
    print(f"Model file not found at: {model_path}")
