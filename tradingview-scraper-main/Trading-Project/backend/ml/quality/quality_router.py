from fastapi import APIRouter
import os
from pathlib import Path
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


@router.get("/research-status")
def get_research_status():
    """Return truthful, lightweight status for the unified research dashboard.

    This endpoint intentionally reports *gates* rather than pretending unfinished
    model stages are available.  The representation-learning project currently
    consumes canonical Dukascopy exports produced by ``backend/research_export.py``.
    """
    default_root = Path(__file__).resolve().parents[3] / "research-data"
    data_root = Path(os.environ.get("RESEARCH_DATA_ROOT", default_root)).expanduser()
    canonical_root = data_root / "canonical" / "dukascopy"
    manifests_root = data_root / "manifests" / "dukascopy"

    parquet_files = []
    manifest_files = []
    if canonical_root.exists():
        parquet_files = list(canonical_root.rglob("*.parquet"))
    if manifests_root.exists():
        manifest_files = list(manifests_root.rglob("*.json"))

    canonical_bytes = 0
    for path in parquet_files:
        try:
            canonical_bytes += path.stat().st_size
        except OSError:
            pass

    return {
        "phase": "Phase 1 — Data & Leakage Gate",
        "engine_branch": "agent/representation-learning-integration",
        "training_source": "Dukascopy BID 1m",
        "live_chart_source": "TradingView/OANDA",
        "research_data_root": str(data_root),
        "canonical_partitions": len(parquet_files),
        "manifest_files": len(manifest_files),
        "canonical_bytes": canonical_bytes,
        "gates": {
            "engine_reuse": "ready",
            "research_export": "ready",
            "canonical_data_validation": "in_progress",
            "causal_htf_and_partial_tests": "in_progress",
            "purged_splits": "pending",
            "leakage_safe_windows": "pending",
            "transformer_pretraining": "locked",
            "embeddings": "locked",
            "retrieval": "locked",
            "evaluation": "locked"
        }
    }


@router.get("/auto-labels")
def fetch_auto_labels():
    """
    Returns list of auto-generated labels from the DB.
    """
    labels_dict = get_all_labels()
    # Convert dict to list for the frontend
    return list(labels_dict.values())
