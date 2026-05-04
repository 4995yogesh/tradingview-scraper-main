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

class RefinementModel(nn.Module):
    def __init__(self):
        super(RefinementModel, self).__init__()
        self.g1 = GatedConv1d(21, 64)
        self.g2 = GatedConv1d(64, 128)
        self.pool = nn.AdaptiveAvgPool1d(1)
        
        self.box_embedding = nn.Sequential(
            nn.Linear(4, 32),
            nn.ReLU()
        )
        self.concat_linear = nn.Sequential(
            nn.Linear(160, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 4) # Refined coordinates
        )

    def forward(self, features, initial_box):
        # features: [B, 50, 21] -> [B, 21, 50]
        x, g1 = self.g1(features.transpose(1, 2))
        x, g2 = self.g2(x)
        cnn_out = self.pool(x).squeeze(-1) # [B, 128]
        
        box_embed = self.box_embedding(initial_box) # [B, 32]
        concat = torch.cat((cnn_out, box_embed), dim=1) # [B, 160]
        refined_box = self.concat_linear(concat)
        return refined_box, [g1, g2]

def train_step(model, batch, optimizer):
    model.train()
    features = batch['features']
    initial_box = batch['box_coords'] # Initial box from detector or previous step
    target_box = batch['box_coords'] # Corrected box from user
    
    # Only train on samples where target != initial (though in this dataset they might be same if not redrawn)
    # Actually, we should use original_box vs user_box here if available.
    # For now, we assume batch contains samples where we want to learn the mapping.
    
    optimizer.zero_grad()
    output, gates = model(features, initial_box)
    
    # Point 10: SmoothL1Loss for boundary refinement
    loss = nn.SmoothL1Loss()(output, target_box)
    
    # Point 12: Residual Gating L1
    l1_gate = sum(g.abs().mean() for g in gates)
    loss += 1e-4 * l1_gate
    
    loss.backward()
    optimizer.step()
    return loss.item()

def refine_predict(model, features_np, initial_box_np):
    model.eval()
    with torch.no_grad():
        features = torch.tensor(features_np, dtype=torch.float32).unsqueeze(0)
        initial_box = torch.tensor(initial_box_np, dtype=torch.float32).unsqueeze(0)
        refined_box, _ = model(features, initial_box)
        return refined_box.squeeze(0).cpu().numpy()