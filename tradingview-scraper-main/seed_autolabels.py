import sys
import os

# Path setup
sys.path.append(os.path.join(os.getcwd(), "Trading-Project", "backend"))

from ml.quality.db import init_db, save_auto_label
from server import clear_consolidations_cache, _compute_box_id_long

init_db()

# Seed a few samples for EURUSD 15m
symbol = "EURUSD"
box_id = "test_1"
save_auto_label(
    box_id=box_id,
    label="GOOD",
    confidence=0.88,
    status="AGREED",
    approved=True,
    interpretation="Structure shows tight consolidation with clear range boundaries and strong rejection wick."
)

# Also clear the server cache
clear_consolidations_cache()

print("Seeded test auto-label and cleared cache.")
