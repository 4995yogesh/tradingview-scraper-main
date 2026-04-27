"""
ml_router.py — FastAPI router for ML label/scoring/status endpoints.

Mount in server.py:
    from ml_router import router as ml_router
    app.include_router(ml_router)
"""

import hashlib
import logging
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

from ml import db as ml_db
from ml import scorer
from ml import trainer
from ml.features import extract_features, FEATURE_VERSION
from ml import llm_translator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml"])


# ── Request / response models ─────────────────────────────────────────────────

class ZoneMeta(BaseModel):
    timeframe:  str
    timeStart:  int       # ms
    timeEnd:    int       # ms
    priceHigh:  float
    priceLow:   float
    exchange:   str = "OANDA"
    symbol:     str = "EURUSD"


class LabelPayload(BaseModel):
    box_id:  str
    label:   str
    zone:    ZoneMeta
    comment: Optional[str] = None
    lesson:  Optional[str] = None

    @validator("label")
    def label_valid(cls, v):
        if v not in ("very_good", "good", "bad", "very_bad"):
            raise ValueError("label must be 'very_good', 'good', 'bad', or 'very_bad'")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_box_id(symbol: str, zone: dict) -> str:
    """sha256(symbol:tf:tStart:tEnd:pH:pL) → first 16 hex chars. 
    Stable for live boxes that expand."""
    key = (
        f"{symbol}:{zone['timeframe']}:"
        f"{zone.get('timeStart', zone.get('time_start_ms'))}:"
        f"{zone.get('timeEnd', zone.get('time_end_ms'))}:"
        f"{float(zone.get('priceHigh', zone.get('price_high') or 0)):.5f}:"
        f"{float(zone.get('priceLow', zone.get('price_low') or 0)):.5f}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _get_candles_for_zone(zone: ZoneMeta):
    """Fetch candles for a zone from the candle DB (existing pipeline)."""
    try:
        from pipeline.data.db import candle_db
        rows = candle_db.get_candles(
            zone.exchange, zone.symbol, zone.timeframe, count=2000
        )
        return rows or []
    except Exception as exc:
        logger.warning("[ml_router] Could not fetch candles for zone: %s", exc)
        return []


def _get_swings_for_zone(zone: ZoneMeta):
    """Return swing rows from server's cached computation."""
    try:
        # Import server's cached swing data
        from pipeline.data.db import candle_db
        rows = candle_db.get_candles(
            zone.exchange, zone.symbol, zone.timeframe, count=2000
        )
        if not rows:
            return []
        rows_sorted = sorted(rows, key=lambda r: int(r["ts"]))
        hi_arr = [float(r["high"]) for r in rows_sorted]
        lo_arr = [float(r["low"]) for r in rows_sorted]
        ts_arr = [int(r["ts"]) for r in rows_sorted]

        swings = []
        n = len(ts_arr)
        for i in range(1, n - 1):
            if hi_arr[i] > hi_arr[i - 1] and hi_arr[i] > hi_arr[i + 1]:
                swings.append({
                    "type": "high",
                    "price": hi_arr[i],
                    "time_ms": ts_arr[i] * 1000,
                    "mitigated": False,
                })
            if lo_arr[i] < lo_arr[i - 1] and lo_arr[i] < lo_arr[i + 1]:
                swings.append({
                    "type": "low",
                    "price": lo_arr[i],
                    "time_ms": ts_arr[i] * 1000,
                    "mitigated": False,
                })
        return swings
    except Exception as exc:
        logger.warning("[ml_router] Could not compute swings for zone: %s", exc)
        return []


def _backfill_features(zone: ZoneMeta, box_id: str) -> bool:
    """
    Compute and store feature vector immediately if not cached.
    Returns True if features were stored (new or existing).
    """
    if ml_db.has_feature(box_id):
        return True

    candles = _get_candles_for_zone(zone)
    swings  = _get_swings_for_zone(zone)

    if not candles:
        logger.warning("[ml_router] No candles for feature backfill of %s", box_id)
        return False

    try:
        zone_dict = {
            "timeframe":  zone.timeframe,
            "timeStart":  zone.timeStart,
            "timeEnd":    zone.timeEnd,
            "priceHigh":  zone.priceHigh,
            "priceLow":   zone.priceLow,
        }
        vec = extract_features(zone_dict, candles, swings)
        
        # Base vector is 18 features. We append 6 neutral LLM features so
        # the baseline length is 24, allowing training to proceed even without comments.
        from ml.llm_translator import NEUTRAL_LLM_FEATURES
        vec.extend(NEUTRAL_LLM_FEATURES)

        ml_db.save_feature_vec(box_id, vec, FEATURE_VERSION)
        logger.info("[ml_router] Feature backfill OK for %s (ver=%s)", box_id, FEATURE_VERSION)
        return True
    except Exception as exc:
        logger.warning("[ml_router] Feature extraction failed for %s: %s", box_id, exc)
        return False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/label")
def label_box(payload: LabelPayload):
    """
    Save a human label. Allows relabeling (no uniqueness enforced).
    Triggers feature backfill if missing.
    Triggers retrain check after save.
    """
    zone_meta = {
        "exchange":  payload.zone.exchange,
        "symbol":    payload.zone.symbol,
        "timeframe": payload.zone.timeframe,
        "timeStart": payload.zone.timeStart,
        "timeEnd":   payload.zone.timeEnd,
        "priceHigh": payload.zone.priceHigh,
        "priceLow":  payload.zone.priceLow,
    }

    # Save label
    label_id = ml_db.save_label(
        box_id=payload.box_id,
        label=payload.label,
        zone_meta=zone_meta,
        comment=payload.comment,
        lesson=payload.lesson,
        feature_ver=FEATURE_VERSION,
        model_version_used=scorer.get_model_version(),
    )
    logger.info("[ml/label] Saved label '%s' for box %s (id=%d)",
                payload.label, payload.box_id, label_id)

    # Invalidate consolidations cache so the chart updates immediately
    try:
        from server import clear_consolidations_cache
        clear_consolidations_cache()
    except Exception:
        pass

    # If this box was in the FP/FN tracking list, remove it now that feedback is given
    try:
        from ml import db as _db
        from ml import trainer as _trainer
        before_fp = len(_trainer.TRAINING_STATE["error_boxes"]["fp"])
        before_fn = len(_trainer.TRAINING_STATE["error_boxes"]["fn"])
        
        _db.clear_error_box(payload.box_id)
        # Update in-memory state
        _trainer.TRAINING_STATE["error_boxes"]["fp"] = [b for b in _trainer.TRAINING_STATE["error_boxes"]["fp"] if b["box_id"] != payload.box_id]
        _trainer.TRAINING_STATE["error_boxes"]["fn"] = [b for b in _trainer.TRAINING_STATE["error_boxes"]["fn"] if b["box_id"] != payload.box_id]
        
        after_fp = len(_trainer.TRAINING_STATE["error_boxes"]["fp"])
        after_fn = len(_trainer.TRAINING_STATE["error_boxes"]["fn"])
        logger.info("[ml/label] Tracking removal: FP %d->%d, FN %d->%d for box %s", 
                    before_fp, after_fp, before_fn, after_fn, payload.box_id)
    except Exception as e:
        logger.warning("[ml/label] Failed to clear error box tracing: %s", e)

    # Feature backfill (immediate, non-blocking since it's fast)
    _backfill_features(payload.zone, payload.box_id)

    # LLM feature enrichment — async, never blocks the label save
    if payload.comment:
        def _enrich():
            try:
                existing_vec = ml_db.get_feature_vec(payload.box_id)
                if existing_vec is not None and len(existing_vec) >= 18:
                    # Snip off the neutral 6 feats to get the pure base 18 feats
                    base_vec = existing_vec[:18]
                    enriched = llm_translator.append_llm_to_vector(
                        base_vec, payload.comment, payload.label
                    )
                    # Store enriched vector under the correct version
                    ml_db.save_feature_vec(payload.box_id, enriched, FEATURE_VERSION)
                    logger.info("[ml/label] LLM enrichment done for %s", payload.box_id)
            except Exception as exc:
                logger.warning("[ml/label] LLM enrichment failed: %s", exc)
        threading.Thread(target=_enrich, daemon=True, name="llm-enricher").start()

    # Auto-train disabled — training is manual only (Force Train button)
    # trainer.maybe_trigger_retrain()

    unconsumed = ml_db.count_unconsumed()
    threshold = trainer.get_retrain_threshold()
    return {
        "success":              True,
        "label_id":             label_id,
        "unconsumed_count":     unconsumed,
        "labels_until_retrain": max(0, threshold - unconsumed),
    }


@router.get("/uncertainty")
def get_uncertainty():
    """
    Return top 10 lowest-confidence unlabeled boxes from latest 200 detected zones.
    """
    try:
        # Pull latest consolidations (internal call to avoid HTTP round-trip)
        from server import get_consolidations_all
        consolidations_resp = get_consolidations_all()
        all_zones = consolidations_resp.get("zones", [])
    except Exception as exc:
        logger.warning("[ml/uncertainty] Could not fetch consolidations: %s", exc)
        return {"status": "ok", "boxes": []}

    if not all_zones:
        return {"status": "ok", "boxes": []}

    # Take latest 200 by timeEnd DESC
    all_zones_sorted = sorted(all_zones, key=lambda z: z.get("timeEnd", 0), reverse=True)
    latest_200 = all_zones_sorted[:200]

    # Filter unlabeled boxes
    box_ids = [z.get("box_id") for z in latest_200 if z.get("box_id")]
    labels_map = ml_db.get_labels_for_boxes(box_ids)
    unlabeled_zones = [
        z for z in latest_200
        if z.get("box_id") and labels_map.get(z["box_id"]) is None
    ]

    if not unlabeled_zones:
        return {"status": "ok", "boxes": []}

    # Batch score
    unlabeled_ids = [z["box_id"] for z in unlabeled_zones]
    scores_map = scorer.batch_score(unlabeled_ids)

    # Attach scores
    for z in unlabeled_zones:
        bid = z.get("box_id")
        z["score"] = scores_map.get(bid, scorer.FALLBACK)

    # Sort: confidence ASC (lowest first), then timeEnd DESC (newest first)
    unlabeled_zones.sort(
        key=lambda z: (
            z["score"]["confidence"],
            -z.get("timeEnd", 0),
        )
    )

    top10 = unlabeled_zones[:10]
    return {"status": "ok", "boxes": top10}


@router.get("/status")
def get_status():
    """Return model version, label progress, and evaluation metrics."""
    checkpoint = ml_db.get_active_model()
    unconsumed  = ml_db.count_unconsumed()
    total       = ml_db.count_all_labels()
    by_class    = ml_db.count_labels_by_class()
    threshold   = trainer.get_retrain_threshold()

    return {
        "model_version":        checkpoint["version"] if checkpoint else None,
        "model_ready":          checkpoint is not None,
        "cold_start":           checkpoint is None,
        "labels_collected":     total,
        "labels_by_class":      by_class,
        "unconsumed_count":     unconsumed,
        "labels_until_retrain": max(0, threshold - unconsumed),
        "precision_good":       checkpoint["precision_good"] if checkpoint else None,
        "recall_good":          checkpoint["recall_good"] if checkpoint else None,
        "support_good":         checkpoint["support_good"] if checkpoint else None,
        "last_trained_at":      checkpoint["trained_at"] if checkpoint else None,
    }


@router.get("/training_progress")
def get_training_progress():
    """Return real-time LightGBM training state and logs."""
    from ml.trainer import TRAINING_STATE
    return TRAINING_STATE


@router.get("/predict")
def predict(box_id: str):
    """Return inference contract for a given box_id."""
    if not box_id:
        raise HTTPException(400, "box_id is required")
    return scorer.score_box(box_id)


@router.post("/retrain")
def manual_retrain():
    """Force training regardless of unconsumed count. Dev/admin use only."""
    if trainer._train_lock.locked():
        return {"status": "already_running"}

    def force_train():
        with trainer._train_lock:
            try:
                from ml.trainer import TRAINING_STATE
                TRAINING_STATE["logs"] = []
                TRAINING_STATE["is_training"] = True
                trainer._run_training(force=True)
            except Exception as exc:
                logger.error("[ml/retrain] Force retrain failed: %s", exc, exc_info=True)
                from ml.trainer import TRAINING_STATE
                TRAINING_STATE["logs"].append(f"Fatal error: {exc}")
            finally:
                from ml.trainer import TRAINING_STATE
                TRAINING_STATE["is_training"] = False

    t = threading.Thread(target=force_train, daemon=True, name="ml-force-trainer")
    t.start()
    return {"status": "triggered"}
