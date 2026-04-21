import json

def find_unconnected():
    with open(r'c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main\graphify-out\graph.html', 'r', encoding='utf-8') as f:
        text = f.read()

    start_str = "const RAW_NODES = ["
    start_idx = text.find(start_str)
    end_idx = text.find("];", start_idx)
    json_str = text[start_idx + 18 : end_idx + 1]
    
    nodes = json.loads(json_str)
    
    files = set()
    for node in nodes:
        if node.get("degree") == 0:
            files.add(node.get("source_file"))
            
    print(",".join([str(x) for x in sorted(files) if x]))

find_unconnected()
