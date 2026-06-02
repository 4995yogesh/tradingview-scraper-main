import sys, json
from graphify.build import build_from_json
from graphify.cluster import score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from pathlib import Path

extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text())
detection  = json.loads(Path('graphify-out/.graphify_detect.json').read_text())
analysis   = json.loads(Path('graphify-out/.graphify_analysis.json').read_text())

G = build_from_json(extraction)
communities = {int(k): v for k, v in analysis['communities'].items()}
cohesion = {int(k): v for k, v in analysis['cohesion'].items()}
tokens = {'input': extraction.get('input_tokens', 0), 'output': extraction.get('output_tokens', 0)}

labels = {
    0:  "Consolidation Box Detection",
    1:  "Backfill & Calibration Pipeline",
    2:  "Chart Data & Live Feed",
    3:  "Training DB & Box Management",
    4:  "React UI Components",
    5:  "Auto-Labeling & Gemini Review",
    6:  "Candle Database Layer",
    7:  "Feature Engineering (43-ch)",
    8:  "ML Router & API Server",
    9:  "Box Engine (Pine-style Heuristic)",
    10: "NN Predictor Pipeline",
    11: "Data Aggregator & Streaming",
    12: "Breakout Detection & Signal Gen",
    13: "Gemini Trainer (LLM Analysis)",
    14: "Agent System (Multi-Agent)",
    15: "Chart Page (Frontend)",
    16: "Box Primitive Renderer",
    17: "Canvas Utilities & Rendering",
    18: "Event Filters & Validation",
    19: "Swing Levels Detection",
}
# Fill remaining small communities generically
for cid in communities:
    if cid not in labels:
        nodes = communities[cid][:2]
        labels[cid] = 'Community ' + str(cid)

questions = suggest_questions(G, communities, labels)

report = generate(G, communities, cohesion, labels, analysis['gods'], analysis['surprises'], detection, tokens, 'Trading-Project', suggested_questions=questions)
Path('graphify-out/GRAPH_REPORT.md').write_text(report)
Path('graphify-out/.graphify_labels.json').write_text(json.dumps({str(k): v for k, v in labels.items()}))
print('Report updated with community labels')
