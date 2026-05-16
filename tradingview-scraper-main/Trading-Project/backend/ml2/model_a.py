import torch
import torch.nn as nn
import numpy as np
import sys
import os

# Add parent dir to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

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
        return h * (1 + g), g # Point 12: Residual Gating + Return gate for L1

class SegmentationModel(nn.Module):
    def __init__(self):
        super(SegmentationModel, self).__init__()
        self.g1 = GatedConv1d(config.FEATURE_COUNT, 64)
        self.g2 = GatedConv1d(64, 128)
        self.lstm = nn.LSTM(128, 64, batch_first=True, bidirectional=True)
        self.fc = nn.Linear(128, 1)

    def forward(self, x):
        # x shape: [B, 100, 43] (Batch, SeqLen, Features)
        assert x.shape[2] == config.FEATURE_COUNT, f"Expected {config.FEATURE_COUNT} features, got {x.shape[2]}"
        assert self.g1.conv.in_channels == config.FEATURE_COUNT, f"Model expects {self.g1.conv.in_channels} channels"
        
        x = x.transpose(1, 2)  # [B, 43, 100]
        x, g1 = self.g1(x)
        x, g2 = self.g2(x)
        x = x.transpose(1, 2)  # [B, 50, 128]
        x, _ = self.lstm(x)
        logits = self.fc(x).squeeze(2)  # [B, 50]
        return logits, [g1, g2]

def dice_loss(logits, targets, eps=1e-8):
    p = torch.sigmoid(logits)
    intersection = (p * targets).sum(dim=1)
    union = p.sum(dim=1) + targets.sum(dim=1)
    dice = (2 * intersection + eps) / (union + eps)
    return 1 - dice.mean()

def train_step(model, batch, optimizer, pos_weight=1.0):
    model.train()
    features = batch['features']
    labels = batch['seg_mask']
    optimizer.zero_grad()
    
    logits, gates = model(features)
    
    # Point 6: Hybrid Loss (0.5 BCE + 0.5 Dice)
    bce_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, device=logits.device))
    bce = bce_fn(logits, labels)
    dice = dice_loss(logits, labels)
    
    loss = 0.5 * bce + 0.5 * dice
    
    # Point 12: L1 Reg on Gates
    l1_gate = sum(g.abs().mean() for g in gates)
    loss += 1e-4 * l1_gate
    
    loss.backward()
    optimizer.step()
    return loss.item()

def predict_heatmap(model, features_np):
    model.eval()
    with torch.no_grad():
        features = torch.from_numpy(features_np).float().unsqueeze(0)
        logits, _ = model(features)
        probabilities = torch.sigmoid(logits).squeeze(0).cpu().numpy()
    return probabilities

def load_model(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model file not found at {path}")
        
    checkpoint = torch.load(path, map_location='cpu')
    
    # Support old models that only saved state_dict
    if "model_state" not in checkpoint:
        print("WARN: Loading legacy model without metadata.")
        model = SegmentationModel()
        model.load_state_dict(checkpoint)
        return model
        
    # Validate metadata
    if checkpoint.get("feature_count") != config.FEATURE_COUNT:
        raise RuntimeError(
            f"Model expects {checkpoint['feature_count']} features but runtime uses {config.FEATURE_COUNT}"
        )
    if checkpoint.get("sequence_length") != config.SEQUENCE_LENGTH:
        raise RuntimeError(
            f"Model expects sequence length {checkpoint['sequence_length']} but runtime uses {config.SEQUENCE_LENGTH}"
        )
        
    model = SegmentationModel()
    model.load_state_dict(checkpoint["model_state"])
    
    print(f"Loaded model version {checkpoint.get('model_version')} successfully.")
    return model