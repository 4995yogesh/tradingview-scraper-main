import json
from pathlib import Path

# Collect all chunk files
chunks = []
for i in range(1, 100):
    cp = Path(f'graphify-out/.graphify_chunk_{i}.json')
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
            if 'nodes' in data and 'edges' in data:
                chunks.append(data)
                print(f'  Chunk {i}: {len(data["nodes"])} nodes, {len(data["edges"])} edges')
        except Exception as e:
            print(f'  Chunk {i}: ERROR - {e}')

all_nodes = []
all_edges = []
all_hyperedges = []
seen_ids = set()
for c in chunks:
    for n in c.get('nodes', []):
        if n['id'] not in seen_ids:
            seen_ids.add(n['id'])
            all_nodes.append(n)
    all_edges.extend(c.get('edges', []))
    all_hyperedges.extend(c.get('hyperedges', []))

# Load cached
cached_path = Path('graphify-out/.graphify_cached.json')
if cached_path.exists():
    cached = json.loads(cached_path.read_text())
    for n in cached.get('nodes', []):
        if n['id'] not in seen_ids:
            seen_ids.add(n['id'])
            all_nodes.append(n)
    all_edges.extend(cached.get('edges', []))
    all_hyperedges.extend(cached.get('hyperedges', []))
    print(f'Cached: {len(cached.get("nodes",[]))} nodes, {len(cached.get("edges",[]))} edges')

result = {
    'nodes': all_nodes,
    'edges': all_edges,
    'hyperedges': all_hyperedges,
    'input_tokens': 0,
    'output_tokens': 0
}
Path('graphify-out/.graphify_semantic.json').write_text(json.dumps(result, indent=2))
print(f'Semantic total: {len(all_nodes)} nodes, {len(all_edges)} edges, {len(all_hyperedges)} hyperedges')
