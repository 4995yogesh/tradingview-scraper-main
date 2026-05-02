import torch
import torch.nn as nn
import numpy as np

class RefinementModel(nn.Module):
    def __init__(self):
        super(RefinementModel, self).__init__()
        self.cnn_encoder = nn.Sequential(
            nn.Conv1d(12, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1)
        )
        self.box_embedding = nn.Sequential(
            nn.Linear(4, 32),
            nn.ReLU()
        )
        self.concat_linear = nn.Sequential(
            nn.Linear(160, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 4)
        )
        self.self_attention = nn.MultiheadAttention(embed_dim=160, num_heads=4)

    def forward(self, features, initial_box):
        features = features.transpose(1, 2)  # [batch, 12, 50]
        features = self.cnn_encoder(features).squeeze(-1)  # [batch, 128]
        box_embed = self.box_embedding(initial_box)  # [batch, 32]
        concat = torch.cat((features, box_embed), dim=1)  # [batch, 160]
        concat = concat.unsqueeze(1)  # [batch, 1, 160]
        attn_output, _ = self.self_attention(concat, concat, concat)  # [batch, 1, 160]
        attn_output = attn_output.squeeze(1)  # [batch, 160]
        refined_box = self.concat_linear(attn_output)  # [batch, 4]
        return refined_box

def train_step(model, features, initial_box, target_box, optimizer):
    optimizer.zero_grad()
    mask = (initial_box != target_box).any(dim=1)
    if mask.any():
        features_filtered = features[mask]
        initial_box_filtered = initial_box[mask]
        target_box_filtered = target_box[mask]
        output = model(features_filtered, initial_box_filtered)
        loss = nn.SmoothL1Loss()(output, target_box_filtered)
        loss.backward()
        optimizer.step()
        return loss.item()
    return 0.0

def refine(model, features_np, initial_box_np):
    model.eval()
    with torch.no_grad():
        features = torch.tensor(features_np, dtype=torch.float32).unsqueeze(0)
        initial_box = torch.tensor(initial_box_np, dtype=torch.float32).unsqueeze(0)
        refined_box = model(features, initial_box).squeeze(0).numpy()
    return refined_box