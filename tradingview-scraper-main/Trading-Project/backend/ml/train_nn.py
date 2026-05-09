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
    "total_samples": 0,
    "train_losses": [],
    "val_losses": [],
    "logs": [],
    "error_boxes": {"fp": [], "fn": []}
}

_train_lock = threading.Lock()

def _log_msg(msg: str):
    logger.info(msg)
    TRAINING_STATE["logs"].append(msg)
    if len(TRAINING_STATE["logs"]) > 200:
        TRAINING_STATE["logs"].pop(0)

def _t_u(t):
    """Convert time to unix timestamp in seconds."""
    if t is None: return 0
    val = 0
    if isinstance(t, (int, float)):
        val = float(t)
    elif isinstance(t, str):
        if 'T' in t and 'Z' in t:
            import datetime
            val = datetime.datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
        elif t.replace('.','',1).isdigit():
            val = float(t)
        else:
            import pandas as pd
            val = pd.to_datetime(t).timestamp()
    else:
        return 0
    
    while val > 5e9:
        val /= 1000.0
    return val

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
    try: db.update_training_progress(status='STARTING')
    except: pass

    try:
        conn = sqlite3.connect('training_set.db')
        cursor = conn.cursor()
        # Include every row that has usable OHLC context.
        # user_box (human-refined) is preferred; original_meta is the fallback.
        # SKIPPED and INVALID_DATA are the only excluded statuses.
        cursor.execute("""
            SELECT box_id, symbol, timeframe, ohlc_context, user_box, original_meta
            FROM review_queue
            WHERE status IN ('LABELED', 'ANALYZED')
        """)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            _log_msg("Error: No usable boxes found in training_set.db")
            db.update_training_progress(status='FAILED', epoch=0, loss=0, val_loss=0)
            return

        labeled_count   = sum(1 for r in rows if r[4])  # rows with user_box
        unlabeled_count = len(rows) - labeled_count
        _log_msg(f"Found {len(rows)} total samples ({labeled_count} human-labeled, {unlabeled_count} ground-truth fallback). Preparing data...")

        sequence_length = 100  # Captures 30+30 context buffer + average box size
        X = []
        y = []

        for row in rows:
            bid, sym, tf, ohlc_json, user_box_json, original_meta_json = row
            try:
                if not ohlc_json:
                    continue

                if user_box_json:
                    user_box = json.loads(user_box_json)
                    boxes_list = user_box if isinstance(user_box, list) else [user_box]
                    if original_meta_json:
                        meta = json.loads(original_meta_json)
                        for b in boxes_list:
                            if 'timeStart' not in b:
                                b['timeStart'] = meta.get('timeStart') or meta.get('time_start_ms')
                            if 'timeEnd' not in b:
                                b['timeEnd'] = meta.get('timeEnd') or meta.get('time_end_ms')
                            if 'priceHigh' not in b:
                                b['priceHigh'] = meta.get('priceHigh') or meta.get('price_high')
                            if 'priceLow' not in b:
                                b['priceLow'] = meta.get('priceLow') or meta.get('price_low')
                    user_box = boxes_list
                elif original_meta_json:
                    meta = json.loads(original_meta_json)
                    # original_meta has the same keys the model needs
                    user_box = [{
                        'timeStart': meta.get('timeStart') or meta.get('time_start_ms'),
                        'timeEnd':   meta.get('timeEnd') or meta.get('time_end_ms'),
                        'priceHigh': meta.get('priceHigh') or meta.get('price_high'),
                        'priceLow':  meta.get('priceLow') or meta.get('price_low'),
                    }]
                else:
                    continue  # no target at all — skip

                ohlc = json.loads(ohlc_json)
                if not ohlc or len(ohlc) < 5:
                    continue

                # Normalize: always work as a list of boxes
                boxes_list = user_box if isinstance(user_box, list) else [user_box]

                all_ts = [_t_u(c['time']) for c in ohlc]

                # Generate one training sample per drawn box
                for box_idx, box in enumerate(boxes_list):
                    try:
                        if not box or 'timeStart' not in box or 'priceHigh' not in box:
                            continue

                        b_start = _t_u(box['timeStart'])
                        b_end   = _t_u(box['timeEnd'])

                        # Find the index of box end in full context
                        end_idx_in_all = int(np.argmin([abs(t - b_end) for t in all_ts]))

                        # Crop 100 candles ending up to 30 candles after box end
                        crop_end   = min(len(ohlc), end_idx_in_all + 30)
                        crop_start = max(0, crop_end - sequence_length)
                        ohlc_window = ohlc[crop_start:crop_end]
                        if len(ohlc_window) < sequence_length:
                            ohlc_window = [ohlc_window[0]] * (sequence_length - len(ohlc_window)) + ohlc_window

                        # Feature matrix (100, 4)
                        feat = np.array([[float(c['open']), float(c['high']), float(c['low']), float(c['close'])] for c in ohlc_window])

                        # Min-Max normalization
                        window_min   = np.min(feat)
                        window_max   = np.max(feat)
                        window_range = max(1e-9, window_max - window_min)
                        feat = (feat - window_min) / window_range

                        # Add positional encoding (100, 5)
                        pos = np.linspace(0, 1, sequence_length).reshape(-1, 1)
                        feat = np.hstack([feat, pos])

                        # Targets: Segmentation Mask + Price Boundaries
                        win_ts = [_t_u(c['time']) for c in ohlc_window]
                        s_idx  = int(np.argmin([abs(t - b_start) for t in win_ts]))
                        e_idx  = int(np.argmin([abs(t - b_end)   for t in win_ts]))

                        # Binary Mask: 1 for consolidation candles, 0 otherwise
                        mask = np.zeros(sequence_length, dtype=np.float32)
                        start_clip = max(0, min(s_idx, e_idx))
                        end_clip   = min(sequence_length - 1, max(s_idx, e_idx))
                        mask[start_clip : end_clip + 1] = 1.0
                        
                        y_high = (float(box['priceHigh']) - window_min) / window_range
                        y_low  = (float(box['priceLow'])  - window_min) / window_range

                        X.append(feat)
                        # Concatenate mask (100) and prices (2) -> (102)
                        y.append(np.concatenate([mask, [y_high, y_low]]))
                    except Exception as be:
                        _log_msg(f"Skipping box #{box_idx} in {bid}: {be}")
                        continue

            except Exception as e:
                _log_msg(f"Skipping row {bid}: {e}")
                continue

        if not X:
            _log_msg("Error: No valid training samples extracted.")
            db.update_training_progress(status='FAILED')
            return

        TRAINING_STATE["total_samples"] = len(X)

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)

        from ml.shared_models import ConsolidationCNN

        model = ConsolidationCNN()
        
        # Loss functions: BCE for heatmap, MSE for prices
        # We use BCEWithLogitsLoss with pos_weight=2.0 to handle class imbalance
        criterion_seg   = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([2.0]))
        criterion_price = nn.MSELoss()
        optimizer       = torch.optim.Adam(model.parameters(), lr=0.001)

        from sklearn.model_selection import train_test_split
        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, random_state=42)

        X_train_t = torch.from_numpy(X_train)
        y_train_t = torch.from_numpy(y_train)
        X_val_t = torch.from_numpy(X_val)
        y_val_t = torch.from_numpy(y_val)

        num_epochs = 300
        TRAINING_STATE["max_iterations"] = num_epochs
        TRAINING_STATE["train_losses"] = []
        TRAINING_STATE["val_losses"] = []
        _log_msg(f"Starting training for {num_epochs} epochs on {len(X_train)} train / {len(X_val)} val samples...")

        for epoch in range(num_epochs):
            model.train()
            optimizer.zero_grad()
            
            # Forward pass
            pred_heatmap, pred_prices = model(X_train_t)
            
            # Split target into mask (100) and prices (2)
            target_mask   = y_train_t[:, :100]
            target_prices = y_train_t[:, 100:]
            
            loss_seg   = criterion_seg(pred_heatmap, target_mask)
            loss_price = criterion_price(pred_prices, target_prices)
            
            # Combined loss: weight segmentation more heavily initially
            loss = loss_seg + 0.5 * loss_price
            
            loss.backward()
            optimizer.step()
            
            # Validation
            model.eval()
            with torch.no_grad():
                v_pred_heatmap, v_pred_prices = model(X_val_t)
                vt_mask   = y_val_t[:, :100]
                vt_prices = y_val_t[:, 100:]
                
                v_loss_seg   = criterion_seg(v_pred_heatmap, vt_mask)
                v_loss_price = criterion_price(v_pred_prices, vt_prices)
                val_loss = v_loss_seg + 0.5 * v_loss_price
            
            TRAINING_STATE["iteration"] = epoch + 1
            TRAINING_STATE["val_logloss"] = float(val_loss.item())
            TRAINING_STATE["train_losses"].append(float(loss.item()))
            TRAINING_STATE["val_losses"].append(float(val_loss.item()))

            if (epoch + 1) % 5 == 0:
                _log_msg(f"Epoch {epoch+1}/{num_epochs}, Train Loss: {loss.item():.6f} (Seg: {loss_seg.item():.4f}, Price: {loss_price.item():.4f}), Val Loss: {val_loss.item():.6f}")

        # Save model
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'models')
        os.makedirs(models_dir, exist_ok=True)
        save_path = os.path.join(models_dir, 'consolidation_nn.pt')
        torch.save(model.state_dict(), save_path)
        
        # Save plot
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10,6))
            plt.plot(range(1, num_epochs+1), TRAINING_STATE["train_losses"], label='Train Loss', color='#2962FF')
            plt.plot(range(1, num_epochs+1), TRAINING_STATE["val_losses"], label='Val Loss', color='#00BFA5')
            plt.title('Training vs Validation Loss (30+30 Context)')
            plt.xlabel('Epoch')
            plt.ylabel('MSE Loss')
            plt.legend()
            plt.grid(True, linestyle='--', alpha=0.7)
            plot_path = os.path.join(models_dir, 'training_val_loss.png')
            plt.savefig(plot_path)
            plt.close()
            _log_msg(f"Plot saved to {plot_path}")
        except Exception as e:
            _log_msg(f"Warning: Failed to plot loss graph: {e}")
        
        try: db.update_training_progress(status='COMPLETED', epoch=num_epochs, loss=float(loss.item()), val_loss=float(val_loss.item()))
        except: pass
        _log_msg(f"Training Completed ✓. Model saved to {save_path}")

    except Exception as e:
        _log_msg(f"FATAL ERROR: {e}")
        try: db.update_training_progress(status='FAILED')
        except: pass
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
