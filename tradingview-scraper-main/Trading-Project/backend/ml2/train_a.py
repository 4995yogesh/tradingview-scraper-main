import sys
import logging
import torch
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
    
    # Point 1: Class Balanced Sampler
    sampler = dataset.get_sampler()
    dataloader = DataLoader(dataset, batch_size=16, sampler=sampler)
    
    model = SegmentationModel()
    optimizer = Adam(model.parameters(), lr=0.001)
    best_loss = float('inf')
    
    # Point 1: pos_weight = (neg_count / pos_count)
    labels = [s['is_consolidation'] for s in dataset.samples]
    neg_count = labels.count(0)
    pos_count = labels.count(1)
    pos_weight = neg_count / (pos_count + 1e-8)
    logging.info(f"Class counts: Neg={neg_count}, Pos={pos_count}. Calculated pos_weight={pos_weight:.2f}")

    os.makedirs(os.path.join(backend_dir, 'data', 'models'), exist_ok=True)
    
    for epoch in range(30):
        epoch_loss = 0.0
        for batch in dataloader:
            loss = train_step(model, batch, optimizer, pos_weight=pos_weight)
            epoch_loss += loss
            
        epoch_loss /= (len(dataloader) or 1)
        if (epoch + 1) % 10 == 0:
            logging.info(f"Epoch {epoch + 1}, Loss: {epoch_loss}")
            
        if epoch_loss < best_loss:
            best_loss = epoch_loss
            model_path = os.path.join(backend_dir, 'data', 'models', 'model_a.pt')
            torch.save(model.state_dict(), model_path)
            logging.info(f"Model saved with loss: {best_loss:.4f}")