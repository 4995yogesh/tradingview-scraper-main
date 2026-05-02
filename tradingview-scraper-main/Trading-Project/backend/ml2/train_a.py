import sys
import logging
from torch.utils.data import DataLoader
from torch.optim import Adam
from dataset import ConsolidationDataset
from model_a import SegmentationModel, train_step

sys.path.append('ml2')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

import os

if __name__ == '__main__':
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, 'training_set.db')
    dataset = ConsolidationDataset(db_path=db_path)
    
    if len(dataset) < 10:
        logging.warning(f"Dataset has less than 10 samples: {len(dataset)}")
    
    dataloader = DataLoader(dataset, batch_size=16, shuffle=True)
    model = SegmentationModel()
    optimizer = Adam(model.parameters(), lr=0.001)
    best_loss = float('inf')
    
    os.makedirs(os.path.join(backend_dir, 'data', 'models'), exist_ok=True)
    
    for epoch in range(200):
        epoch_loss = 0.0
        for batch in dataloader:
            features = batch['features']
            seg_mask = batch['seg_mask']
            loss = train_step(model, {'features': features, 'seg_mask': seg_mask}, optimizer, pos_weight=2.0)
            epoch_loss += loss
            
        epoch_loss /= len(dataloader)
        if (epoch + 1) % 10 == 0:
            logging.info(f"Epoch {epoch + 1}, Loss: {epoch_loss}")
            
        if epoch_loss < best_loss:
            best_loss = epoch_loss
            model_path = os.path.join(backend_dir, 'data', 'models', 'model_a.pt')
            import torch
            torch.save(model.state_dict(), model_path)
            logging.info(f"Model saved to {model_path} with loss: {best_loss}")