import torch
import torch.nn as nn
import numpy as np
import json
import sqlite3
import os
import sys

# Add parent dir to path to import TrainingDB
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from training_db import TrainingDB

def train():
    db = TrainingDB(db_path='training_set.db')
    db.update_training_progress(status='STARTING')

    conn = sqlite3.connect('training_set.db')
    cursor = conn.cursor()
    cursor.execute('SELECT box_id, ohlc_context, user_box FROM review_queue WHERE status = "LABELED"')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        db.update_training_progress(status='FAILED', epoch=0, loss=0, val_loss=0)
        return

    sequence_length = 100
    X = []
    y = []

    for row in rows:
        _, ohlc_json, user_box_json = row
        ohlc = json.loads(ohlc_json)[-sequence_length:]
        user_box = json.loads(user_box_json)
        
        if len(ohlc) < sequence_length:
            continue

        # Feature matrix (100, 4)
        feat = np.array([[c['open'], c['high'], c['low'], c['close']] for c in ohlc])
        first_close = feat[0, 3]
        feat = (feat - first_close) / first_close # Normalize
        
        # Targets
        if isinstance(user_box, dict):
            user_box = [user_box]
        
        # We take the first box for now as target
        box = user_box[0]
        
        # Find indices
        times = [c['time'] for c in ohlc]
        try:
            # Map time to index in the 100-candle window
            s_idx = np.argmin([abs(t - (box['timeStart']/1000 if box['timeStart'] > 2e12 else box['timeStart'])) for t in times])
            e_idx = np.argmin([abs(t - (box['timeEnd']/1000 if box['timeEnd'] > 2e12 else box['timeEnd'])) for t in times])
            
            y_high = (box['priceHigh'] - first_close) / first_close
            y_low  = (box['priceLow'] - first_close) / first_close
            
            X.append(feat)
            y.append([s_idx/100.0, e_idx/100.0, y_high, y_low])
        except Exception as e:
            print(f"Skipping box due to index error: {e}")
            continue

    if not X:
        db.update_training_progress(status='FAILED')
        return

    X = np.array(X) # (N, 100, 4)
    y = np.array(y) # (N, 4)

    # Model
    class ConsolidationCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv1d(4, 32, kernel_size=3, padding=1),
                nn.BatchNorm1d(32),
                nn.ReLU(),
                nn.Conv1d(32, 64, kernel_size=3, padding=1),
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1)
            )
            self.fc = nn.Linear(64, 4)

        def forward(self, x):
            x = x.transpose(1, 2) # (N, 4, 100)
            x = self.conv(x)      # (N, 64, 1)
            x = x.squeeze(-1)     # (N, 64)
            return self.fc(x)     # (N, 4)

    model = ConsolidationCNN()
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    X_t = torch.tensor(X, dtype=torch.float32)
    y_t = torch.tensor(y, dtype=torch.float32)

    epochs = 100
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        pred = model(X_t)
        loss = criterion(pred, y_t)
        loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 5 == 0:
            db.update_training_progress(status='TRAINING', epoch=epoch+1, loss=float(loss.item()))
            print(f"Epoch {epoch+1}/{epochs}, Loss: {loss.item():.6f}")

    # Save
    os.makedirs('models', exist_ok=True)
    torch.save(model.state_dict(), 'models/consolidation_nn.pt')
    db.update_training_progress(status='COMPLETED', epoch=epochs, loss=float(loss.item()))
    print("Training Completed ✓")

if __name__ == "__main__":
    train()
