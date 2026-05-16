import os
import sys
import torch
import torch.nn as nn
import numpy as np
import sqlite3

# Add ml2 to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(backend_dir, 'ml2'))
sys.path.append(os.path.join(backend_dir, 'ml'))

from model_a import SegmentationModel, dice_loss
from dataset import ConsolidationDataset
from torch.utils.data import DataLoader

def find_hard_samples():
    db_path = os.path.join(backend_dir, 'training_set.db')
    model_path = os.path.join(backend_dir, 'data', 'models', 'model_a.pt')
    
    if not os.path.exists(model_path):
        print("Model file not found!")
        return
        
    dataset = ConsolidationDataset(db_path=db_path)
    dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
    
    model = SegmentationModel()
    model.load_state_dict(torch.load(model_path, map_location='cpu'))
    model.eval()
    
    # Get box_ids and info from DB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT box_id, symbol, timeframe FROM review_queue WHERE status IN ('LABELED','ANALYZED','SKIPPED')")
    db_rows = cursor.fetchall()
    conn.close()
    
    losses = []
    bce_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([3.0])) # using same pos_weight as train_nn
    
    with torch.no_grad():
        for i, batch in enumerate(dataloader):
            features = batch['features']
            labels = batch['seg_mask']
            
            logits, gates = model(features)
            
            bce = bce_fn(logits, labels)
            dice = dice_loss(logits, labels)
            loss = 0.5 * bce + 0.5 * dice
            
            losses.append({
                'index': i,
                'loss': loss.item(),
                'box_id': db_rows[i][0] if i < len(db_rows) else 'N/A',
                'symbol': db_rows[i][1] if i < len(db_rows) else 'N/A',
                'tf': db_rows[i][2] if i < len(db_rows) else 'N/A'
            })
            
    # Sort by loss descending
    losses.sort(key=lambda x: x['loss'], reverse=True)
    
    print("Top 5 Hardest Samples (Highest Loss):")
    for j in range(min(5, len(losses))):
        print(f"Rank {j+1}: Loss: {losses[j]['loss']:.6f}, Symbol: {losses[j]['symbol']}, TF: {losses[j]['tf']}, Box ID: {losses[j]['box_id']}")
        
if __name__ == "__main__":
    find_hard_samples()
