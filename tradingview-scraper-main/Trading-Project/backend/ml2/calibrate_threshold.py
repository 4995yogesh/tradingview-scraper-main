import os
import sys
import torch
import numpy as np
from torch.utils.data import DataLoader

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from model_d import QualityScorer, score_predict
from dataset import ConsolidationDataset
from evaluation_metrics import evaluate_batch

def calibrate():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    model_path = os.path.join(backend_dir, 'data', 'models', 'model_d.pt')
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    dataset = ConsolidationDataset(db_path=db_path)
    dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
    
    model = QualityScorer().to(device)
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location=device))
        print(f"Loaded Model D from {model_path}")
    else:
        print("Model D not found.")
        return

    model.eval()
    
    samples_for_eval = []
    
    print("Gathering predictions...")
    with torch.no_grad():
        for batch in dataloader:
            features = batch['features'].to(device)
            box_coords = batch['box_coords'].to(device)
            target_score = batch['quality_score'].item()
            is_con = batch['is_consolidation'].item()
            
            # Use raw score for calibration
            score, valid_logits, _ = model(features, box_coords)
            pred_score = score.item()
            
            samples_for_eval.append({
                "pred_box": box_coords.squeeze().cpu().numpy().tolist(), # dummy for metric compatibility
                "true_box": box_coords.squeeze().cpu().numpy().tolist(), # dummy
                "pred_score": pred_score,
                "true_quality": target_score,
                "is_consolidation": is_con
            })

    best_f1 = -1
    best_t = 0.5
    
    print("\nThreshold Sweep:")
    print("T\tF1\tRejAcc\tFPR")
    print("-" * 30)
    
    for t in np.linspace(0.1, 0.9, 9):
        res = evaluate_batch(samples_for_eval, threshold=t)
        f1 = res['f1_score']
        rej = res['rejection_accuracy']
        fpr = res['false_positive_rate']
        print(f"{t:.1f}\t{f1:.3f}\t{rej:.3f}\t{fpr:.3f}")
        
        if f1 > best_f1:
            best_f1 = f1
            best_t = t
            
    print("-" * 30)
    print(f"Optimal Threshold: {best_t:.1f} (F1: {best_f1:.3f})")

if __name__ == "__main__":
    calibrate()
