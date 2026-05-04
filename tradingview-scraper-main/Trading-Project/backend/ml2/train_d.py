import os
import sys
import torch
import torch.optim as optim
from torch.utils.data import DataLoader

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from model_d import QualityScorer, train_step
from dataset import ConsolidationDataset

def train_d():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    dataset = ConsolidationDataset(db_path=db_path)
    if len(dataset) < 10:
        print("Not enough samples for training Model D.")
        return

    # Point 1: Class Balanced Sampler
    sampler = dataset.get_sampler()
    dataloader = DataLoader(dataset, batch_size=16, sampler=sampler)
    
    model = QualityScorer().to(device)
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    labels = [s['is_consolidation'] for s in dataset.samples]
    print(f"Training Model D (Dual Head) | Neg={labels.count(0)}, Pos={labels.count(1)}")

    for epoch in range(30):
        total_loss = 0.0
        for batch in dataloader:
            # Batch items are sent to device inside train_step or here
            # For simplicity, we ensure tensors are on device
            batch_dev = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
            loss = train_step(model, batch_dev, optimizer)
            total_loss += loss

        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1}, Loss: {total_loss/len(dataloader)}")

    model_path = os.path.join(backend_dir, 'data', 'models', 'model_d.pt')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    torch.save(model.state_dict(), model_path)
    print(f"Model D saved to {model_path}")

if __name__ == "__main__":
    train_d()