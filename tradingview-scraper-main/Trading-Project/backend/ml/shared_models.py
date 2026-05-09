import torch
import torch.nn as nn

class ConsolidationCNN(nn.Module):
    def __init__(self, sequence_length=100):
        super().__init__()
        self.sequence_length = sequence_length
        
        # Encoder: Extract features while maintaining temporal resolution
        self.encoder = nn.Sequential(
            nn.Conv1d(5, 32, kernel_size=3, padding=1),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Conv1d(64, 64, kernel_size=5, padding=2), # Broader context
            nn.BatchNorm1d(64),
            nn.ReLU()
        )
        
        # Segmentation Head: (N, 64, 100) -> (N, 1, 100)
        # Predicts probability per candle
        self.segmentation_head = nn.Conv1d(64, 1, kernel_size=1)
        
        # Price Head: Global price boundaries
        self.price_head = nn.Sequential(
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 2) # high, low
        )

    def forward(self, x):
        # x shape: (N, 100, 5) -> (N, 5, 100) for Conv1d
        x = x.transpose(1, 2)
        features = self.encoder(x)
        
        # Heatmap (Logits)
        heatmap = self.segmentation_head(features).squeeze(1) # (N, 100)
        
        # Price regression
        prices = self.price_head(features) # (N, 2)
        
        return heatmap, prices
