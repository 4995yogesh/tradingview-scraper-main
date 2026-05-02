import torch
import torch.nn as nn
import numpy as np
import json
import sqlite3
import os
import sys
import threading
import logging

# Add parent dir to path to import TrainingDB
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from training_db import TrainingDB

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Training Real-Time State (Matches trainer.py for UI compatibility) ────────
TRAINING_STATE = {
    "is_training": False,
    "iteration": 0,
    "max_iterations": 100,
    "val_logloss": 0.0,
    "logs": [],
    "error_boxes": {"fp": [], "fn": []}
}

_train_lock = threading.Lock()

def _log_msg(msg: str):
    logger.info(msg)
    TRAINING_STATE["logs"].append(msg)
    if len(TRAINING_STATE["logs"]) > 200:
        TRAINING_STATE["logs"].pop(0)

def train(force=False):
    """
    Main training function. 
    If force=True, bypass minimum label check.
    """
    db = TrainingDB(db_path='training_set.db')
    TRAINING_STATE["is_training"] = True
    TRAINING_STATE["iteration"] = 0
    TRAINING_STATE["logs"] = []
    
    _log_msg("=== Starting Neural Network Training ===")
    db.update_training_progress(status='STARTING')

    try:
        conn = sqlite3.connect('training_set.db')
        cursor = conn.cursor()
        cursor.execute('SELECT box_id, symbol, timeframe, ohlc_context, user_box FROM review_queue WHERE status IN ("LABELED", "ANALYZED")')
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            _log_msg("Error: No labeled boxes found in training_set.db")
            db.update_training_progress(status='FAILED', epoch=0, loss=0, val_loss=0)
            return

        _log_msg(f"Found {len(rows)} labeled samples. Preparing data...")

        sequence_length = 50  # Most stored contexts are 56-58 candles; use 50 to include all samples
        X = []
        y = []

        for row in rows:
            bid, sym, tf, ohlc_json, user_box_json = row
            try:
                if not ohlc_json or not user_box_json:
                    continue
                
                ohlc = json.loads(ohlc_json)
                user_box = json.loads(user_box_json)
                
                if len(ohlc) < 5:  # Need at least 5 candles
                    continue
                
                # Take last sequence_length candles; if shorter, pad with first candle
                if len(ohlc) >= sequence_length:
                    ohlc = ohlc[-sequence_length:]
                else:
                    pad = [ohlc[0]] * (sequence_length - len(ohlc))
                    ohlc = pad + ohlc

                # Feature matrix (100, 4)
                feat = np.array([[float(c['open']), float(c['high']), float(c['low']), float(c['close'])] for c in ohlc])
                
                # Min-Max normalization
                window_min = np.min(feat)  # Global min of the OHLC block
                window_max = np.max(feat)  # Global max of the OHLC block
                window_range = max(1e-9, window_max - window_min)
                
                feat = (feat - window_min) / window_range  # Normalize
                
                # Targets
                if isinstance(user_box, list):
                    box = user_box[0] if user_box else None
                else:
                    box = user_box
                
                if not box or 'timeStart' not in box or 'priceHigh' not in box:
                    continue
                
                # Find indices — handle ISO strings ("2026-04-22T16:42:00Z") or numeric unix ts
                from datetime import datetime, timezone
                def _to_unix(t):
                    if isinstance(t, str):
                        try:
                            return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
                        except Exception:
                            return 0.0
                    v = float(t)
                    return v / 1000 if v > 2e12 else v

                times = [_to_unix(c['time']) for c in ohlc]
                
                # Normalize box time formats (ms vs s or ISO)
                b_start = _to_unix(box['timeStart'])
                b_end   = _to_unix(box['timeEnd'])
                
                s_idx = np.argmin([abs(t - b_start) for t in times])
                e_idx = np.argmin([abs(t - b_end) for t in times])
                
                y_high = (float(box['priceHigh']) - window_min) / window_range
                y_low  = (float(box['priceLow']) - window_min) / window_range
                
                X.append(feat)
                y.append([s_idx/float(sequence_length), e_idx/float(sequence_length), y_high, y_low])
            except Exception as e:
                _log_msg(f"Skipping box {bid} due to error: {e}")
                continue

        if not X:
            _log_msg("Error: No valid training samples extracted.")
            db.update_training_progress(status='FAILED')
            return

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)

        # Model definition
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
                x = x.transpose(1, 2) # (N, 4, seq_len)
                x = self.conv(x)      # (N, 64, 1)
                x = x.squeeze(-1)     # (N, 64)
                return self.fc(x)

        model = ConsolidationCNN()
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        X_t = torch.from_numpy(X)
        y_t = torch.from_numpy(y)

        epochs = 100
        TRAINING_STATE["max_iterations"] = epochs
        _log_msg(f"Starting training for {epochs} epochs...")

        for epoch in range(epochs):
            model.train()
            optimizer.zero_grad()
            pred = model(X_t)
            loss = criterion(pred, y_t)
            loss.backward()
            optimizer.step()
            
            TRAINING_STATE["iteration"] = epoch + 1
            TRAINING_STATE["val_logloss"] = float(loss.item())

            if (epoch + 1) % 5 == 0:
                db.update_training_progress(status='TRAINING', epoch=epoch+1, loss=float(loss.item()))
                _log_msg(f"Epoch {epoch+1}/{epochs}, Loss: {loss.item():.6f}")

        # Save
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'models')
        os.makedirs(models_dir, exist_ok=True)
        save_path = os.path.join(models_dir, 'consolidation_nn.pt')
        torch.save(model.state_dict(), save_path)
        
        db.update_training_progress(status='COMPLETED', epoch=epochs, loss=float(loss.item()))
        _log_msg(f"Training Completed ✓. Model saved to {save_path}")

    except Exception as e:
        _log_msg(f"FATAL ERROR: {e}")
        db.update_training_progress(status='FAILED')
    finally:
        TRAINING_STATE["is_training"] = False

def train_async(force=False):
    if _train_lock.locked():
        _log_msg("Training already in progress. Ignoring trigger.")
        return
    
    def run():
        with _train_lock:
            train(force=force)
            
    t = threading.Thread(target=run, daemon=True, name="NN-Trainer")
    t.start()
    return t

if __name__ == "__main__":
    train()
