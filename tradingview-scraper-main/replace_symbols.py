import os
import glob

replacements = {
    '"OANDA:EURUSD"': '"OANDA:EURUSD"',
    '"OANDA:EURUSD"': '"OANDA:EURUSD"',
    '"OANDA:EURUSD"': '"OANDA:EURUSD"',
    'exchange="BINANCE",\n            symbol="BTCUSDT"': 'exchange="OANDA",\n            symbol="EURUSD"',
    'exchange="BINANCE",\n        symbol="BTCUSDT"': 'exchange="OANDA",\n        symbol="EURUSD"',
    'exchange="OANDA", symbol="EURUSD"': 'exchange="OANDA", symbol="EURUSD"',
    '"exchange": "OANDA", "symbol": "EURUSD"': '"exchange": "OANDA", "symbol": "EURUSD"'
}

files_to_check = glob.glob("**/*.py", recursive=True) + glob.glob("**/*.md", recursive=True) + glob.glob("**/tv_html.txt", recursive=True)

for file in files_to_check:
    if "venv" in file or ".git" in file or "node_modules" in file:
        continue
    try:
        with open(file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        orig_content = content
        for k, v in replacements.items():
            content = content.replace(k, v)
        
        if content != orig_content:
            with open(file, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated {file}")
    except Exception as e:
        pass
