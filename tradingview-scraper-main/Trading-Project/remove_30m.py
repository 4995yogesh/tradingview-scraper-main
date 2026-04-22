import os
import re

files_to_update = [
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/pipeline/data/collector.py',
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/frontend/src/lib/swingLevels.js',
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/frontend/src/data/chartData.js',
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/frontend/src/components/chart/ChartWidget.jsx',
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/frontend/src/components/chart/ChartToolbar.jsx',
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/frontend/src/components/chart/ChartPage.jsx',
    'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend/server.py'
]

for fpath in files_to_update:
    if os.path.exists(fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # safely handle removals
        content = re.sub(r'[\'\" ]+30m[\'\"]+:\s*\d+,?\s*', '', content)
        content = re.sub(r'[\'\" ]+30m[\'\"]+:\s*[\'\"]30M[\'\"],?\s*', '', content)
        content = re.sub(r'[\'\" ]+30m[\'\"]+:\s*[\'\"]30m[\'\"],?\s*', '', content)
        content = re.sub(r'[\'\" ]+30[\'\"]+:\s*[\'\"]30m[\'\"],?\s*', '', content)
        content = re.sub(r'[\'\"]30m[\'\"],\s*', '', content)
        content = re.sub(r',\s*[\'\"]30m[\'\"]', '', content)
        
        # fix specific cases in server.py
        content = re.sub(r'\"30m\": \"30m\",\s*', '', content)
        content = re.sub(r',\s*\"30m\"', '', content)
        
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Cleaned {fpath}')
