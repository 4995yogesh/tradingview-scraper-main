import os
import sys
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

# Ensure local imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from model_d import QualityScorer
from dataset import ConsolidationDataset

def train_d():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    dataset = ConsolidationDataset(db_path=db_path)
    if len(dataset) < 10:
        print("Not enough samples for training Model D.")
        return

    dataloader = DataLoader(dataset, batch_size=16, shuffle=True)
    model = QualityScorer().to(device)
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    print(f"Training Model D on {len(dataset)} samples...")

    for epoch in range(30):
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
            print(f"Epoch {epoch+1}, Loss: {total_loss/len(dataloader)}")

    model_path = os.path.join(backend_dir, 'data', 'models', 'model_d.pt')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    torch.save(model.state_dict(), model_path)
    print(f"Model D saved to {model_path}")

if __name__ == "__main__":
    train_d()