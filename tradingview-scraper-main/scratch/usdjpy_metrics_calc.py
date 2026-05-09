import os
import sys
import json
import sqlite3
import torch
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

ROOT_DIR = r"c:\Users\ysssi\Downloads\Compressed\tradingview-scraper-main\tradingview-scraper-main"
BACKEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "backend")
ML2_DIR = os.path.join(BACKEND_DIR, "ml2")
DB_PATH = os.path.join(ROOT_DIR, "Trading-Project", "data", "candles.db")

sys.path.append(BACKEND_DIR)
sys.path.append(ML2_DIR)
sys.path.append(os.path.join(ROOT_DIR, "Trading-Project", "project"))

import ml2.inference as inference
from indicators.consolidation import consolidation_boxes

def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM candles WHERE symbol='USDJPY' AND timeframe='15m' ORDER BY ts ASC LIMIT 1000"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [{
        "time": r["ts"] * 1000,
        "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"]
    } for r in rows]

def calculate_iou(box1, box2):
    s1, e1 = box1[0], box1[1]
    s2, e2 = box2[0], box2[1]
    inter_s, inter_e = max(s1, s2), min(e1, e2)
    if inter_e <= inter_s: return 0.0
    inter = inter_e - inter_s
    union = (e1 - s1) + (e2 - s2) - inter
    return inter / union

def run():
    data = load_data()
    df = pd.DataFrame(data)
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    df.set_index('time', inplace=True)
    h_boxes = consolidation_boxes(df).to_dict('records')
    
    ml_boxes = []
    for i in range(50, len(data), 5):
        window = data[i-50:i]
        pred = inference.predict(window)
        if pred and pred.get('confidence', 0) > 0.4:
            s_idx = next((idx for idx, c in enumerate(data) if c['time'] == pred['timeStart']), None)
            e_idx = next((idx for idx, c in enumerate(data) if c['time'] == pred['timeEnd']), None)
            if s_idx is not None and e_idx is not None:
                ml_boxes.append([s_idx, e_idx])

    print(f"Heuristic boxes found: {len(h_boxes)}")
    print(f"ML boxes found: {len(ml_boxes)}")

    # Precision: How many ML boxes match a Heuristic box
    tp_p = 0
    for ml in ml_boxes:
        if any(calculate_iou(ml, [h['start'], h['end']]) > 0.3 for h in h_boxes):
            tp_p += 1
    precision = tp_p / len(ml_boxes) if ml_boxes else 0

    # Recall: How many Heuristic boxes are found by ML
    tp_r = 0
    for h in h_boxes:
        if any(calculate_iou([h['start'], h['end']], ml) > 0.3 for ml in ml_boxes):
            tp_r += 1
    recall = tp_r / len(h_boxes) if h_boxes else 0
    
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    metrics = {
        "precision": precision,
        "recall": recall,
        "f1": f1
    }
    print(json.dumps(metrics))

if __name__ == "__main__":
    run()
