"""
Trading Intelligence API — optimized.

Changes:
  - asyncio.Lock guards all shared-state mutations (was plain mutable dict — not thread-safe)
  - Added GET /candles endpoint (frontend hook calls this)
  - Added GET /consolidations endpoint (frontend hook calls this)
  - Added GET /health endpoint
  - Cache-Control: no-cache on /scenarios (prevents browser caching stale data)
  - CORS credentials fixed to False when origins=["*"]
  - Scenarios now always include: type, entry, sl, tp_zone, path, confirmed, rr_ratio
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("API")

# ── Shared engine state (guarded by lock) ────────────────────────────────────
_state_lock = asyncio.Lock()

# Shape: { tf: { "scenarios": [...], "candles": [...], "consolidations": [...] } }
latest_engine_output: Dict[str, Dict] = {
    tf: {"scenarios": [], "candles": [], "consolidations": []}
    for tf in ["1m", "5m", "15m", "1H", "4H"]
}


async def update_engine_output(tf: str, scenarios: list, candles: list, consolidations: list = None) -> None:
    """Thread-safe update of the shared engine state."""
    async with _state_lock:
        latest_engine_output[tf]["scenarios"]     = scenarios
        latest_engine_output[tf]["candles"]        = candles
        latest_engine_output[tf]["consolidations"] = consolidations or []


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Multi-Timeframe Trading Intelligence API",
    description="Real-time scenario projections for EURUSD",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # Must be False when origins=["*"] — browser rejects True
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Quick liveness check."""
    return {"status": "ok"}


@app.get("/scenarios")
async def get_scenarios(response: Response) -> Dict[str, Any]:
    """
    Returns the latest scenario projections grouped by timeframe.
    Shape: { "1m": [...scenarios], "5m": [...], ... }
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    async with _state_lock:
        return {
            tf: data["scenarios"]
            for tf, data in latest_engine_output.items()
        }


@app.get("/candles")
async def get_candles(
    tf: str = Query("1m", description="Timeframe: 1m|5m|15m|1H|4H"),
    limit: int = Query(250, ge=10, le=500),
    response: Response = None,
) -> Dict[str, Any]:
    """
    Returns the latest N closed candles for the given timeframe.
    Each candle: { timestamp, open, high, low, close }
    """
    if response:
        response.headers["Cache-Control"] = "no-cache"
    valid_tfs = {"1m", "5m", "15m", "1H", "4H"}
    if tf not in valid_tfs:
        return {"status": "error", "message": f"Invalid timeframe. Use one of: {valid_tfs}"}

    async with _state_lock:
        candles = latest_engine_output[tf]["candles"]
        return {
            "status": "ok",
            "timeframe": tf,
            "count": len(candles),
            "candles": candles[-limit:],
        }


@app.get("/consolidations")
async def get_consolidations(response: Response = None) -> Dict[str, Any]:
    """
    Returns detected consolidation zones for all active timeframes.
    Each zone: { timeframe, priceLow, priceHigh, timeStart, timeEnd }
    """
    if response:
        response.headers["Cache-Control"] = "no-cache"
    async with _state_lock:
        zones = []
        for tf, data in latest_engine_output.items():
            zones.extend(data.get("consolidations", []))
        return {"status": "ok", "count": len(zones), "zones": zones}
