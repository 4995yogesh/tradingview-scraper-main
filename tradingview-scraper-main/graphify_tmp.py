import sys
import json
from pathlib import Path

# Step 3A: AST Extraction
from graphify.extract import collect_files, extract

code_files = []
try:
    detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding='utf-8'))
    for f in detect.get('files', {}).get('code', []):
        f_path = Path(f)
        code_files.extend(collect_files(f_path) if f_path.is_dir() else [f_path])
        
    if code_files:
        result = extract(code_files, cache_root=Path('.'))
        Path('graphify-out/.graphify_ast.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    else:
        Path('graphify-out/.graphify_ast.json').write_text(json.dumps({'nodes':[],'edges':[],'input_tokens':0,'output_tokens':0}), encoding='utf-8')
except Exception as e:
    print(f"Error in AST extraction: {e}")
    sys.exit(1)

# Part C - Merge (Since no semantic, just use AST)
try:
    ast = json.loads(Path('graphify-out/.graphify_ast.json').read_text(encoding='utf-8'))
    merged = {
        'nodes': ast['nodes'],
        'edges': ast['edges'],
        'hyperedges': [],
        'input_tokens': 0,
        'output_tokens': 0,
    }
    Path('graphify-out/.graphify_extract.json').write_text(json.dumps(merged, indent=2), encoding='utf-8')
except Exception as e:
    print(f"Error in Merge: {e}")
    sys.exit(1)

# Step 4 - Build graph, cluster, analyze, generate outputs
try:
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.report import generate
    from graphify.export import to_json

    extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text(encoding='utf-8'))
    detection  = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding='utf-8'))

    G = build_from_json(extraction)
    if G.number_of_nodes() == 0:
        print('ERROR: Graph is empty')
        sys.exit(1)

    communities = cluster(G)
    cohesion = score_all(G, communities)
    tokens = {'input': 0, 'output': 0}
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    labels = {cid: 'Community ' + str(cid) for cid in communities}
    questions = suggest_questions(G, communities, labels)

    report = generate(G, communities, cohesion, labels, gods, surprises, detection, tokens, '.', suggested_questions=questions)
    Path('graphify-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
    to_json(G, communities, 'graphify-out/graph.json')

    analysis = {
        'communities': {str(k): v for k, v in communities.items()},
        'cohesion': {str(k): v for k, v in cohesion.items()},
        'gods': gods,
        'surprises': surprises,
        'questions': questions,
    }
    Path('graphify-out/.graphify_analysis.json').write_text(json.dumps(analysis, indent=2), encoding='utf-8')
except Exception as e:
    print(f"Error in Build/Cluster: {e}")
    sys.exit(1)

# Step 6 - HTML
try:
    from graphify.export import to_html
    to_html(G, communities, 'graphify-out/graph.html', community_labels=labels)
except Exception as e:
    print(f"Error generating HTML: {e}")

print("Graph complete.")
