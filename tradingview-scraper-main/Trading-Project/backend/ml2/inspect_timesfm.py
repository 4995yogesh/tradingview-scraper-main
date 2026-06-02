"""
TimeFM Module Inspector v2 — correct attribute path
pred.tfm = SafeTimesFM (IS the TimesFM_2p5_200M_torch)
"""
import os, sys
os.environ["JAX_PLATFORMS"] = "cpu"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import torch

print("=" * 60)
print("TimeFM Module Inspector v2")
print("=" * 60)

from timesfm_predictor import TimesFMPredictor

print("\n[1/4] Loading model...")
pred  = TimesFMPredictor(context_len=512, horizon_len=1)
model = pred.tfm   # SafeTimesFM IS the TimesFM_2p5_200M_torch

print(f"  model type: {type(model)}")
print(f"  model MRO: {[c.__name__ for c in type(model).__mro__]}")

print("\n[2/4] Model Attributes and internal dict keys:")
print(f"dir(model): {dir(model)}")
if hasattr(model, "__dict__"):
    print(f"model.__dict__.keys(): {list(model.__dict__.keys())}")
for attr in dir(model):
    val = getattr(model, attr)
    if "Module" in type(val).__name__ or "model" in attr.lower():
        print(f"Found attribute: {attr} of type {type(val)}")

# Let's also look for torch modules inside any internal predictor objects
if hasattr(model, "model"):
    print("Found model.model attribute! Attributes of model.model:")
    print(dir(model.model))
    if hasattr(model.model, "named_modules"):
        print("model.model has named_modules!")


inner_model = model.model
mock = np.sin(np.linspace(0, 4 * np.pi, 512)).astype(np.float32)

print("\n[4/4] Testing hook on final transformer block (stacked_xf[-1]):")
handles = []
cache = {}

# Register hook on model.model.stacked_xf[-1]
final_block = inner_model.stacked_xf[-1]
def hook_fn(module, input, output):
    if isinstance(output, tuple):
        cache['final_block'] = tuple(t.detach().cpu() if isinstance(t, torch.Tensor) else t for t in output)
    else:
        cache['final_block'] = output.detach().cpu()

handle = final_block.register_forward_hook(hook_fn)


try:
    with torch.no_grad():
        # forecast() expects a list of 1D arrays for inputs
        model.forecast(horizon=1, inputs=[mock])
except Exception as e:
    print(f"  forecast() error: {e}")


handle.remove()

if 'final_block' in cache:
    out = cache['final_block']
    print(f"  Hook on stacked_xf[-1] fired!")
    print(f"  Output type: {type(out)}")
    if isinstance(out, tuple):
        print(f"  Output is tuple of len {len(out)}")
        for idx, item in enumerate(out):
            if isinstance(item, torch.Tensor):
                print(f"    item[{idx}] is Tensor of shape {tuple(item.shape)}")
            else:
                print(f"    item[{idx}] is {type(item)}")
    elif isinstance(out, torch.Tensor):
        print(f"  Output is Tensor of shape {tuple(out.shape)}")
        pooled = out.mean(dim=1)
        print(f"  Mean-pooled shape: {tuple(pooled.shape)}")
else:
    print("  Hook on stacked_xf[-1] did NOT fire.")


print("\n" + "=" * 60)
print("DONE")
print("=" * 60)

