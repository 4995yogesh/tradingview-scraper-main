import torch
import torch.nn as nn
import numpy as np

class GatedConv1d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=3, padding=1):
        super().__init__()
        self.conv = nn.Conv1d(in_channels, out_channels, kernel_size, padding=padding)
        self.gate = nn.Conv1d(in_channels, out_channels, kernel_size, padding=padding)
        self.bn = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU()

    def forward(self, x):
        h = self.relu(self.bn(self.conv(x)))
        g = torch.sigmoid(self.gate(x))
        return h * (1 + g), g

class QualityScorer(nn.Module):
    def __init__(self):
        super(QualityScorer, self).__init__()
        self.g1 = GatedConv1d(30, 64)
        self.g2 = GatedConv1d(64, 128)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.flatten = nn.Flatten()
        
        self.box_encoder = nn.Sequential(
            nn.Linear(4, 16),
            nn.ReLU()
        )
        
        # Point 5: Dual Head Architecture
        # Score Head for Regression (0..1)
        self.score_head = nn.Sequential(
            nn.Linear(144, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )
        # Class Head for Validity Classification
        self.class_head = nn.Sequential(
            nn.Linear(144, 32),
            nn.ReLU(),
            nn.Linear(32, 1) # Logits for BCE
        )

    def forward(self, features, box_coords):
        # features: [B, 50, 21] -> [B, 21, 50]
        x, g1 = self.g1(features.transpose(1, 2))
        x, g2 = self.g2(x)
        cnn_out = self.flatten(self.pool(x))
        
        box_out = self.box_encoder(box_coords)
        concat_out = torch.cat((cnn_out, box_out), dim=1)
        
        score = self.score_head(concat_out).squeeze(1)
        valid_logits = self.class_head(concat_out).squeeze(1)
        
        return score, valid_logits, [g1, g2]

def train_step(model, batch, optimizer):
    model.train()
    features = batch['features']
    box_coords = batch['box_coords']
    target_score = batch['quality_score'].squeeze()
    target_is_con = batch['is_consolidation'].squeeze().float()
    
    optimizer.zero_grad()
    score, valid_logits, gates = model(features, box_coords)
    
    # Point 5: Hybrid Loss
    mse_loss = nn.MSELoss()(score, target_score)
    bce_loss = nn.BCEWithLogitsLoss()(valid_logits, target_is_con)
    
    loss = 0.5 * mse_loss + 0.5 * bce_loss
    
    # Point 12: Residual Gating L1 Reg
    l1_gate = sum(g.abs().mean() for g in gates)
    loss += 1e-4 * l1_gate
    
    loss.backward()
    optimizer.step()
    return loss.item()

def score_predict(model, features_np, box_np):
    model.eval()
    with torch.no_grad():
        features = torch.tensor(features_np, dtype=torch.float32).unsqueeze(0)
        box_coords = torch.tensor(box_np, dtype=torch.float32).unsqueeze(0)
        score, valid_logits, _ = model(features, box_coords)
        
        # Valid flag: both regression score and classification head agree
        is_valid = (score.item() > 0.5) and (torch.sigmoid(valid_logits).item() > 0.5)
        return score.item(), is_valid