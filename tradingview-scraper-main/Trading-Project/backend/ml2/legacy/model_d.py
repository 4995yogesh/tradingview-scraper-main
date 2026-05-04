import torch
import torch.nn as nn
import numpy as np

class QualityScorer(nn.Module):
    def __init__(self):
        super(QualityScorer, self).__init__()
        self.cnn_encoder = nn.Sequential(
            nn.Conv1d(12, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten()
        )
        self.box_encoder = nn.Sequential(
            nn.Linear(4, 16),
            nn.ReLU()
        )
        self.mlp = nn.Sequential(
            nn.Linear(144, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, features, box_coords):
        # features: [batch, 50, 12] -> [batch, 12, 50]
        cnn_out = self.cnn_encoder(features.transpose(1, 2))
        box_out = self.box_encoder(box_coords)
        concat_out = torch.cat((cnn_out, box_out), dim=1)
        quality_score = self.mlp(concat_out).squeeze(1)
        return quality_score

def train_step(model, features, box_coords, target_quality, optimizer):
    model.train()
    optimizer.zero_grad()
    output = model(features, box_coords)
    loss = nn.MSELoss()(output.squeeze(), target_quality)
    loss.backward()
    optimizer.step()
    return loss.item()

def score(model, features_np, box_np):
    model.eval()
    with torch.no_grad():
        features = torch.tensor(features_np, dtype=torch.float32).unsqueeze(0)
        box_coords = torch.tensor(box_np, dtype=torch.float32).unsqueeze(0)
        output = model(features, box_coords)
        return output.item()