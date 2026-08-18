from fastapi import APIRouter
import os
from .autolabel.storage import get_all_labels

router = APIRouter(prefix="/api/ml/quality", tags=["ml_quality"])

@router.get("/status")
def get_quality_status():
    return {
        "model_name": "Consolidation Quality v1 (Regression)",
        "type": "Regression",
        "description": "Learns from structure (range, volatility, boundaries, efficiency)",
        "version": "1.0.0"
    }

@router.get("/auto-labels")
def fetch_auto_labels():
    """
    Returns list of auto-generated labels from the DB.
    """
    labels_dict = get_all_labels()
    # Convert dict to list for the frontend
    return list(labels_dict.values())
