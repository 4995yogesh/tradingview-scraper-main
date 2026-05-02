import sys, os
sys.path.insert(0, 'ml2')
from dataset import ConsolidationDataset

ds = ConsolidationDataset(db_path='training_set.db')
print(f"Dataset samples: {len(ds)}")
if len(ds) > 0:
    item = ds[0]
    print(f"features shape: {item['features'].shape}")
    print(f"seg_mask shape: {item['seg_mask'].shape}")
    print(f"quality_score: {item['quality_score']}")
    print(f"is_consolidation: {item['is_consolidation']}")
else:
    print("ERROR: Dataset is empty")
