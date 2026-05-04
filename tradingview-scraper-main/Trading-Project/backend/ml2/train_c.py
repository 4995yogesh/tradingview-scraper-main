import os
import sys
import torch
import torch.optim as optim
from torch.utils.data import DataLoader
import numpy as np

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from model_c import RefinementModel, train_step
from dataset import ConsolidationDataset
from model_a import SegmentationModel

def train_c():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    model_a_path = os.path.join(backend_dir, 'data', 'models', 'model_a.pt')
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # Load Model A for generating initial boxes
    model_a = SegmentationModel().to(device)
    if os.path.exists(model_a_path):
        model_a.load_state_dict(torch.load(model_a_path, map_location=device))
    model_a.eval()

    dataset = ConsolidationDataset(db_path=db_path)
    # Filter for positive samples only
    dataset.samples = [s for s in dataset.samples if s['is_consolidation'] == 1]
    
    if len(dataset) < 10:
        print("Not enough samples for training Model C.")
        return

    dataloader = DataLoader(dataset, batch_size=16, shuffle=True)
    model = RefinementModel().to(device)
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    print(f"Training Model C on {len(dataset)} positive samples...")

    for epoch in range(30):
        total_loss = 0.0
        for batch in dataloader:
            # Note: We need a mapping from initial_box to target_box.
            # In this dataset, 'box_coords' IS the target.
            # We use Model A to generate the 'initial_box' (prediction) and learn to refine it to 'box_coords'.
            
            features = batch['features'].to(device)
            target_box = batch['box_coords'].to(device)
            
            with torch.no_grad():
                logits, _ = model_a(features)
                heatmaps = torch.sigmoid(logits).cpu().numpy()
                initial_boxes = []
                for i in range(features.size(0)):
                    h = heatmaps[i]
                    thresholded = h > 0.5
                    if np.any(thresholded):
                        idxs = np.where(thresholded)[0]
                        si, ei = idxs[0], idxs[-1]
                    else:
                        si, ei = 0, 49
                    initial_boxes.append([si/50.0, ei/50.0, 0.5, 0.5])
                
                initial_boxes_tensor = torch.tensor(initial_boxes, dtype=torch.float32).to(device)
            
            # Create a custom batch for train_step
            batch_c = {
                'features': features,
                'box_coords': initial_boxes_tensor, # input to refinement
                'target_coords': target_box      # ground truth
            }
            
            # Since model_c.train_step uses batch['box_coords'] as input and target, we adjust.
            # I'll update model_c.train_step to be more explicit.
            
            optimizer.zero_grad()
            output, gates = model(features, initial_boxes_tensor)
            loss = torch.nn.SmoothL1Loss()(output, target_box)
            l1_gate = sum(g.abs().mean() for g in gates)
            loss += 1e-4 * l1_gate
            
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1}, Loss: {total_loss/len(dataloader)}")

    model_path = os.path.join(backend_dir, 'data', 'models', 'model_c.pt')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    torch.save(model.state_dict(), model_path)
    print(f"Model C saved to {model_path}")

if __name__ == "__main__":
    train_c()