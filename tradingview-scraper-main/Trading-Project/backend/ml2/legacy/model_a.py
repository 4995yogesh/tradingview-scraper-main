import torch
import torch.nn as nn
import numpy as np

class SegmentationModel(nn.Module):
    def __init__(self):
        super(SegmentationModel, self).__init__()
        self.conv1 = nn.Conv1d(12, 64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(64)
        self.relu = nn.ReLU()
        self.conv2 = nn.Conv1d(64, 128, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm1d(128)
        self.lstm = nn.LSTM(128, 64, batch_first=True, bidirectional=True)
        self.fc = nn.Linear(128, 1)

    def forward(self, x):
        x = x.transpose(1, 2)  # [batch, 12, 50]
        x = self.relu(self.bn1(self.conv1(x)))
        x = self.relu(self.bn2(self.conv2(x)))
        x = x.transpose(1, 2)  # [batch, 50, 128]
        x, _ = self.lstm(x)
        x = self.fc(x).squeeze(2)  # [batch, 50]
        return x

def train_step(model, batch, optimizer, pos_weight=2.0):
    model.train()
    features = batch['features']
    labels = batch['seg_mask']
    optimizer.zero_grad()
    logits = model(features)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight))
    loss = loss_fn(logits, labels)
    loss.backward()
    optimizer.step()
    return loss.item()

def predict_heatmap(model, features_np):
    model.eval()
    with torch.no_grad():
        features = torch.from_numpy(features_np).float().unsqueeze(0)  # [1, 50, 12]
        logits = model(features).squeeze(0)  # [50]
        probabilities = torch.sigmoid(logits).numpy()  # [50]
    return probabilities