import torch
import torch.nn as nn
import numpy as np
import json
import sqlite3
import os
import sys
import threading
import logging
import time
from collections import deque
from torch.utils.data import DataLoader

# Add parent dir to path to import TrainingDB
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from training_db import TrainingDB
import config

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
    "error_boxes": {"fp": [], "fn": []},
    "avg_epoch_time": 0.0,
    "eta_seconds": 0,
    "samples_per_second": 0.0,
    "status": "IDLE",
    "stop_requested": False
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
        import sys
        import os
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ml2_dir = os.path.join(backend_dir, 'ml2')
        if ml2_dir not in sys.path:
            sys.path.append(ml2_dir)
            
        from dataset import ConsolidationDataset
        from model_a import SegmentationModel, dice_loss
        db_path = os.path.abspath(os.path.join(backend_dir, 'training_set.db'))
        _log_msg(f"Loading dataset from: {db_path}")
        dataset = ConsolidationDataset(db_path=db_path)
        if len(dataset) < 10:
            _log_msg(f"Warning: Dataset has less than 10 samples: {len(dataset)}")
            
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        _log_msg(f"Using device: {device}")
        
        from sklearn.model_selection import train_test_split
        from torch.utils.data import Subset, WeightedRandomSampler
        
        indices = list(range(len(dataset)))
        train_idx, val_idx = train_test_split(indices, test_size=0.2, shuffle=False)
        
        train_dataset = Subset(dataset, train_idx)
        val_dataset = Subset(dataset, val_idx)
        
        # Compute weights for train_dataset
        train_samples = [dataset.samples[i] for i in train_idx]
        labels = [s['is_consolidation'] for s in train_samples]
        neg_count = labels.count(0)
        pos_count = labels.count(1)
        
        # Load hard samples for priority weighting
        hard_ids = set()
        try:
            models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'models')
            hard_samples_path = os.path.join(models_dir, 'hard_samples.json')
            if os.path.exists(hard_samples_path):
                with open(hard_samples_path, 'r') as f:
                    hard_samples = json.load(f)
                    hard_ids = set(s['box_id'] for s in hard_samples)
                    _log_msg(f"Loaded {len(hard_ids)} hard samples for priority weighting")
        except Exception as e:
            _log_msg(f"WARN Error loading hard samples for weighting: {e}")

        if neg_count > 0 and pos_count > 0:
            neg_weight = 1.0 / neg_count
            pos_weight = 1.0 / pos_count
            
            weights = []
            for s in train_samples:
                w = pos_weight if s['is_consolidation'] == 1 else neg_weight
                if s.get('box_id') in hard_ids:
                    w *= 3.0 # Give 3x priority to hard samples
                weights.append(w)
            
            sampler = WeightedRandomSampler(weights, len(weights))
        else:
            sampler = None
            
        dataloader = DataLoader(
            train_dataset, 
            batch_size=64, 
            sampler=sampler,
            shuffle=True if sampler is None else False,
            num_workers=4 if device.type == 'cuda' else 0,
            pin_memory=True if device.type == 'cuda' else False
        )
        
        val_dataloader = DataLoader(
            val_dataset,
            batch_size=64,
            shuffle=False,
            num_workers=4 if device.type == 'cuda' else 0,
            pin_memory=True if device.type == 'cuda' else False
        )
        
        model = SegmentationModel().to(device)
        
        # Option A: Reduced pos_weight to stop aggressive predictions at the edges
        pos_weight = 3.0
        criterion_seg = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight], device=device))
        criterion_price = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        
        # AMP Scaler
        scaler = torch.cuda.amp.GradScaler() if device.type == 'cuda' else None

        from sklearn.model_selection import train_test_split
        num_epochs = 300
        TRAINING_STATE["max_iterations"] = num_epochs
        TRAINING_STATE["train_losses"] = []
        TRAINING_STATE["val_losses"] = []
        _log_msg(f"Starting training for {num_epochs} epochs on {len(dataset)} samples...")

        epoch_times = deque(maxlen=10)
        TRAINING_STATE["status"] = "TRAINING"
        
        best_loss = float('inf')
        patience = 20
        patience_counter = 0

        spike_samples = {} # box_id -> epoch
        for epoch in range(num_epochs):
            if TRAINING_STATE.get("stop_requested", False):
                _log_msg("Stop requested. Terminating training...")
                TRAINING_STATE["is_training"] = False
                TRAINING_STATE["status"] = "STOPPED"
                TRAINING_STATE["stop_requested"] = False
                break
                
            model.train()
            epoch_loss = 0.0
            epoch_start = time.time()
            
            for batch in dataloader:
                batch_start = time.time()
                
                # Move batch to device
                batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
                features = batch['features']
                labels = batch['seg_mask']
                
                optimizer.zero_grad()
                
                # Mixed Precision
                if scaler is not None:
                    with torch.cuda.amp.autocast():
                        logits, gates = model(features)
                        bce = criterion_seg(logits, labels)
                        dice = dice_loss(logits, labels)
                        loss = 0.5 * bce + 0.5 * dice
                        l1_gate = sum(g.abs().mean() for g in gates)
                        loss += 1e-4 * l1_gate
                        
                    scaler.scale(loss).backward()
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    logits, gates = model(features)
                    bce = criterion_seg(logits, labels)
                    dice = dice_loss(logits, labels)
                    loss = 0.5 * bce + 0.5 * dice
                    l1_gate = sum(g.abs().mean() for g in gates)
                    loss += 1e-4 * l1_gate
                    
                    loss.backward()
                    optimizer.step()
                
                epoch_loss += loss.item()
                
                # Spike detection
                if loss.item() > 0.5:
                    if 'box_id' in batch:
                        for bid in batch['box_id']:
                            if bid != 'N/A':
                                spike_samples[bid] = epoch + 1
                
                batch_duration = time.time() - batch_start
                batch_size = len(batch['features']) if 'features' in batch else 16
                samples_per_second = batch_size / (batch_duration or 0.001)
                TRAINING_STATE["samples_per_second"] = samples_per_second
                
            epoch_loss /= (len(dataloader) or 1)
            
            # Validation Loop
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for v_batch in val_dataloader:
                    v_batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in v_batch.items()}
                    v_features = v_batch['features']
                    v_labels = v_batch['seg_mask']
                    
                    v_logits, _ = model(v_features)
                    v_bce = criterion_seg(v_logits, v_labels)
                    v_dice = dice_loss(v_logits, v_labels)
                    v_l = 0.5 * v_bce + 0.5 * v_dice
                    val_loss += v_l.item()
            val_loss /= (len(val_dataloader) or 1)
            
            epoch_duration = time.time() - epoch_start
            epoch_times.append(epoch_duration)
            avg_epoch_time = sum(epoch_times) / len(epoch_times)
            
            remaining_epochs = num_epochs - (epoch + 1)
            eta_seconds = remaining_epochs * avg_epoch_time
            
            TRAINING_STATE["iteration"] = epoch + 1
            TRAINING_STATE["val_logloss"] = float(val_loss)
            TRAINING_STATE["train_losses"].append(float(epoch_loss))
            TRAINING_STATE["val_losses"].append(float(val_loss))
            TRAINING_STATE["avg_epoch_time"] = avg_epoch_time
            TRAINING_STATE["eta_seconds"] = int(eta_seconds)
            
            if (epoch + 1) % 10 == 0:
                _log_msg(f"Epoch {epoch+1}/{num_epochs}, Loss: {epoch_loss:.6f}")
                
            # Early Stopping disabled as requested
            pass

        # Save model with metadata
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'models')
        os.makedirs(models_dir, exist_ok=True)
        save_path = os.path.join(models_dir, 'model_a.pt')
        
        checkpoint = {
            "model_state": model.state_dict(),
            "feature_count": config.FEATURE_COUNT,
            "sequence_length": config.SEQUENCE_LENGTH,
            "model_version": config.MODEL_VERSION,
            "feature_names": config.FEATURES,
            "feature_signature": config.FEATURE_SIGNATURE
        }
        
        # Atomic swap to prevent reading partially written files
        tmp_path = os.path.join(models_dir, 'model_tmp.pt')
        torch.save(checkpoint, tmp_path)
        os.replace(tmp_path, save_path)
        _log_msg(f"Model saved atomically with metadata to {save_path}")
        
        # Update live inference model in memory to avoid restart
        try:
            import inference
            inference.model_a = model
            _log_msg("INFO  Live inference model updated in memory ✓")
        except Exception as e:
            _log_msg(f"WARN  Could not update live inference model: {e}")
        
        # Save plot
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10,6))
            num_actual_epochs = len(TRAINING_STATE["train_losses"])
            plt.plot(range(1, num_actual_epochs+1), TRAINING_STATE["train_losses"], label='Train Loss', color='#2962FF')
            plt.plot(range(1, num_actual_epochs+1), TRAINING_STATE["val_losses"], label='Val Loss', color='#00BFA5')
            plt.title('Training vs Validation Loss (30+30 Context)')
            plt.xlabel('Epoch')
            plt.ylabel('MSE Loss')
            plt.legend()
            plt.grid(True, linestyle='--', alpha=0.7)
            plot_path = os.path.join(models_dir, 'training_val_loss.png')
            plt.savefig(plot_path)
            plt.close()
            _log_msg(f"Plot saved to {plot_path}")
            
            # Save timestamped plot for history
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M')
                plot_path_ts = os.path.join(models_dir, f'training_val_loss_{timestamp}.png')
                plt.figure(figsize=(10,6))
                plt.plot(range(1, num_actual_epochs+1), TRAINING_STATE["train_losses"], label='Train Loss', color='#2962FF')
                plt.plot(range(1, num_actual_epochs+1), TRAINING_STATE["val_losses"], label='Val Loss', color='#00BFA5')
                plt.title('Training vs Validation Loss')
                plt.xlabel('Epoch')
                plt.ylabel('MSE Loss')
                plt.legend()
                plt.grid(True, linestyle='--', alpha=0.7)
                plt.savefig(plot_path_ts)
                plt.close()
                _log_msg(f"Timestamped plot saved to {plot_path_ts}")
            except Exception as e:
                _log_msg(f"WARN  Could not save timestamped plot: {e}")

            # Find hard samples and save to hard_samples.json
            try:
                from model_a import dice_loss
                
                dataloader_eval = DataLoader(dataset, batch_size=1, shuffle=False)
                
                # Get box_ids from DB
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT box_id FROM review_queue WHERE status IN ('LABELED','ANALYZED','SKIPPED')")
                db_rows = cursor.fetchall()
                conn.close()
                
                losses = []
                bce_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([3.0]))
                
                with torch.no_grad():
                    for i, batch in enumerate(dataloader_eval):
                        features = batch['features']
                        labels = batch['seg_mask']
                        
                        logits, _ = model(features)
                        
                        bce = bce_fn(logits, labels)
                        dice = dice_loss(logits, labels)
                        loss = 0.5 * bce + 0.5 * dice
                        
                        bid = db_rows[i][0] if i < len(db_rows) else 'N/A'
                        label = f"Spike at Epoch {spike_samples[bid]}" if bid in spike_samples else "High Loss"
                        losses.append({
                            'loss': float(loss.item()),
                            'box_id': bid,
                            'label': label
                        })
                        
                # Sort by loss descending and take top 20
                losses.sort(key=lambda x: x['loss'], reverse=True)
                top_20 = losses[:20]
                
                hard_samples_path = os.path.join(models_dir, 'hard_samples.json')
                with open(hard_samples_path, 'w') as f:
                    json.dump(top_20, f, indent=4)
                _log_msg(f"Saved top 20 hard samples to {hard_samples_path}")
                
            except Exception as e:
                _log_msg(f"WARN  Could not find hard samples: {e}")
        except Exception as e:
            _log_msg(f"Warning: Failed to plot loss graph: {e}")
        
        try: db.update_training_progress(status='COMPLETED', epoch=num_epochs, loss=float(epoch_loss), val_loss=float(epoch_loss))
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
