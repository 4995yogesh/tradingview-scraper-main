import json

path = r'C:\Users\ysssi\.gemini\antigravity\brain\fe4cdd4d-e90f-4f8d-a3bb-a3d046e9437c\.system_generated\steps\265\content.md'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    data = json.loads(lines[-1].strip())
    
matches = [z for z in data['zones'] if z['timeframe'] == '1m' and z['timeStart'] == 1777049520000]
print(f"Matches for 1777049520000 1m: {matches}")
