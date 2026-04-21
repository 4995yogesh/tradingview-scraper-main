import os
import glob
from collections import defaultdict

def check():
    with open('unconnected_list.txt', 'r', encoding='utf-8') as f:
        unconnected = [line.strip() for line in f if line.strip()]
        
    # Build list of target identifiers
    targets = {}
    for f in unconnected:
        basename = os.path.basename(f)
        name_no_ext = os.path.splitext(basename)[0]
        # For React components, they might be imported as 'Accordion' instead of 'accordion'
        targets[f] = {basename, name_no_ext, name_no_ext.capitalize(), name_no_ext.lower(), basename.lower()}

    all_files = []
    for ext in ["*.py", "*.jsx", "*.js", "*.html", "*.ts", "*.tsx"]:
        all_files.extend(glob.glob(f"**/{ext}", recursive=True))
        
    usage = defaultdict(list)
    for p in all_files:
        if 'node_modules' in p or '.git' in p or 'graphify-out' in p or p.endswith('check_usage.py') or p.endswith('unconnected_list.txt') or p.endswith('graph.html'):
            continue
            
        try:
            with open(p, 'r', encoding='utf-8') as f:
                content = f.read()
                
            for unconn_file, search_set in targets.items():
                if os.path.normpath(unconn_file) == os.path.normpath(p):
                    continue # don't check a file against itself
                    
                for term in search_set:
                    if term in content:
                        usage[unconn_file].append(p)
                        break # File unconn_file is mentioned in p
        except Exception:
            pass

    import json
    with open('usage_report.json', 'w', encoding='utf-8') as f:
        json.dump(usage, f, indent=2)

if __name__ == "__main__":
    check()
