import os
import sys
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import time
import numpy as np

# Ensure local imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from evaluation_metrics import evaluate_batch

def train_version(version_name, dataset_cls, model_cls):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    print(f"\n--- Training {version_name} ---")
    dataset = dataset_cls(db_path=db_path)
    dataloader = DataLoader(dataset, batch_size=16, shuffle=True)
    model = model_cls().to(device)
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    start_time = time.time()
    
    for epoch in range(100):
        total_loss = 0.0
        for batch in dataloader:
            features = batch['features'].to(device)
            box = batch['box_coords'].to(device)
            target = batch['quality_score'].to(device)

            optimizer.zero_grad()
            output = model(features, box)
            loss = criterion(output, target.float().view_as(output))
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        
        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1}, Loss: {total_loss/len(dataloader):.6f}")

    duration = time.time() - start_time
    
    # ── Final Evaluation Pass ────────────────────────────────────────────────
    model.eval()
    all_eval_samples = []
    with torch.no_grad():
        for batch in dataloader:
            features = batch['features'].to(device)
            box = batch['box_coords'].to(device)
            target = batch['quality_score'].to(device)
            is_consol = batch['is_consolidation'].to(device)

            output = model(features, box)
            
            # Prepare for evaluate_batch
            preds = output.cpu().numpy().flatten()
            trues = target.cpu().numpy().flatten()
            is_c = is_consol.cpu().numpy().flatten()
            p_boxes = box.cpu().numpy()
            
            for i in range(len(preds)):
                all_eval_samples.append({
                    "pred_box": p_boxes[i].tolist(),
                    "true_box": p_boxes[i].tolist(),
                    "pred_score": float(preds[i]),
                    "true_quality": float(trues[i]),
                    "is_consolidation": int(is_c[i])
                })
    
    metrics = evaluate_batch(all_eval_samples)
    return metrics, duration

if __name__ == "__main__":
    # Import Legacy
    from legacy.dataset import ConsolidationDataset as LegacyDataset
    from legacy.model_d import QualityScorer as LegacyModel
    
    # Import New
    from dataset import ConsolidationDataset as NewDataset
    from model_d import QualityScorer as NewModel
    
    # Run Legacy
    legacy_metrics, legacy_time = train_version("Legacy (12-ch)", LegacyDataset, LegacyModel)
    
    # Run New
    new_metrics, new_time = train_version("v2.1 (21-ch)", NewDataset, NewModel)
    
    print("\n" + "="*50)
    print(f"{'METRIC':<20} | {'LEGACY':<12} | {'V2.1':<12} | {'DIFF'}")
    print("-" * 50)
    
    m_list = ["accuracy", "f1_score", "precision", "recall", "score_mse", "final_score"]
    for m in m_list:
        l_v = legacy_metrics[m]
        n_v = new_metrics[m]
        diff = n_v - l_v
        if m == "score_mse": # Lower is better
            status = " [↑]" if diff < 0 else " [↓]"
        else:
            status = " [↑]" if diff > 0 else " [↓]"
        print(f"{m:<20} | {l_v:<12.6f} | {n_v:<12.6f} | {diff:+.6f}{status}")
    
    print("="*50)
    print(f"Total Time: Legacy {legacy_time:.1f}s vs V2.1 {new_time:.1f}s")
