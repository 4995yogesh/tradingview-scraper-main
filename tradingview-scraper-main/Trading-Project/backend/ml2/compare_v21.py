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
from dataset import ConsolidationDataset
from model_d import QualityScorer

def benchmark_v21():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    print(f"\n--- Benchmarking ML2 v2.1 Stabilization ---")
    dataset = ConsolidationDataset(db_path=db_path)
    
    # 1. Train v2.1
    sampler = dataset.get_sampler()
    dataloader = DataLoader(dataset, batch_size=16, sampler=sampler)
    
    model = QualityScorer().to(device)
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    start_time = time.time()
    epochs = 30
    
    print(f"Training on {len(dataset)} samples (Balanced)...")
    for epoch in range(epochs):
        total_loss = 0.0
        for batch in dataloader:
            features = batch['features'].to(device)
            box = batch['box_coords'].to(device)
            target_score = batch['quality_score'].to(device)
            is_con = batch['is_consolidation'].to(device)

            optimizer.zero_grad()
            score, valid_logits, gates = model(features, box)
            
            mse_loss = nn.MSELoss()(score, target_score.squeeze())
            bce_loss = nn.BCEWithLogitsLoss()(valid_logits, is_con.squeeze().float())
            loss = 0.5 * mse_loss + 0.5 * bce_loss
            
            l1_gate = sum(g.abs().mean() for g in gates)
            loss += 1e-4 * l1_gate
                
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        
        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1}, Loss: {total_loss/len(dataloader):.6f}")

    duration = time.time() - start_time
    
    # 2. Evaluate
    model.eval()
    all_eval_samples = []
    eval_loader = DataLoader(dataset, batch_size=1, shuffle=False)
    
    with torch.no_grad():
        for batch in eval_loader:
            features = batch['features'].to(device)
            box = batch['box_coords'].to(device)
            target = batch['quality_score'].to(device)
            is_consol = batch['is_consolidation'].to(device)

            score, _, _ = model(features, box)
            
            all_eval_samples.append({
                "pred_box": box.squeeze().cpu().numpy().tolist(),
                "true_box": box.squeeze().cpu().numpy().tolist(),
                "pred_score": float(score.item()),
                "true_quality": float(target.item()),
                "is_consolidation": int(is_consol.item())
            })
    
    metrics = evaluate_batch(all_eval_samples)
    
    print("\n" + "="*50)
    print(f"{'V2.1 STABILIZATION REPORT':^50}")
    print("="*50)
    print(f"{'METRIC':<25} | {'VALUE':<12}")
    print("-" * 50)
    
    m_list = ["accuracy", "f1_score", "rejection_accuracy", "false_positive_rate", "score_mse"]
    for m in m_list:
        val = metrics.get(m, 0.0)
        print(f"{m:<25} | {val:<12.4f}")
    
    print("-" * 50)
    print(f"TP: {metrics['tp']} | FP: {metrics['fp']} | TN: {metrics['tn']} | FN: {metrics['fn']}")
    print("="*50)
    print(f"Total Training Time: {duration:.1f}s")

if __name__ == "__main__":
    benchmark_v21()
