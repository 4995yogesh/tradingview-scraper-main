"""
Multi-Timeframe Engine — main entry point (optimized).

Changes:
  1. Uses modern FastAPI lifespan (replaces deprecated @app.on_event)
  2. Eliminates duplicate get_candles() calls per cycle (fetch once, reuse)
  3. Extracts consolidation zones per-timeframe and pushes them to the API
  4. Uses update_engine_output() for thread-safe state writes
  5. Fetch logic uses dashboard chart source via backend API, running continuously
"""
import asyncio
import logging
import time
import json
import urllib.request
from contextlib import asynccontextmanager

import uvicorn
from api.server import app, update_engine_output
from data.fetcher import fetcher_instance
from scenarios import generator
from confirmation import mtf
from alerts.manager import alert_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("TradingEngine")

TIMEFRAMES = ["4H", "1H", "15m", "5m", "1m"]

# MTF confirmation mappings: LTF → HTF
MTF_MAP = {
    "1m":  "15m",
    "5m":  "1H",
    "15m": "4H",
}


async def run_engine_cycle() -> None:
    """
    One full analysis cycle:
      1. Fetch candles for all timeframes (once per TF — no double calls)
      2. Generate raw scenarios per TF
      3. Apply MTF confirmation
      4. Detect consolidation zones per TF
      5. Push results to API state atomically
      6. Fire alerts
    """
    # ── Step 1+2: Fetch candles and generate raw scenarios ───────────────────
    candles_by_tf:  dict = {}
    raw_scenarios:  dict = {}

    for tf in TIMEFRAMES:
        candles = fetcher_instance.get_candles(tf, limit=200)
        candles_by_tf[tf]  = candles
        raw_scenarios[tf]  = generator.generate_scenarios(candles) if len(candles) >= 15 else []

    # ── Step 3: MTF confirmation ─────────────────────────────────────────────
    confirmed_scenarios: dict = {}
    for tf in TIMEFRAMES:
        htf = MTF_MAP.get(tf)
        if htf and htf in raw_scenarios and raw_scenarios[htf]:
            confirmed_scenarios[tf] = mtf.confirm_mtf(raw_scenarios[tf], raw_scenarios[htf])
        else:
            confirmed_scenarios[tf] = raw_scenarios[tf]

    # ── Step 4+5: Consolidation zones + atomic state push ───────────────────
    for tf in TIMEFRAMES:
        candles = candles_by_tf[tf]
        scenarios = confirmed_scenarios[tf]

        from strategy.consolidation import detect_all_consolidations
        # Extract consolidation zones for this API endpoint
        consolidations_for_tf = []
        if len(candles) >= 8:
            active_boxes = detect_all_consolidations(candles)
            for box in active_boxes:
                consolidations_for_tf.append({
                    "timeframe":  tf,
                    "priceHigh":  box["top"],
                    "priceLow":   box["bottom"],
                    "timeStart":  box["timeStart"],
                    "timeEnd":    box["timeEnd"],
                })

        await update_engine_output(tf, scenarios, candles, consolidations_for_tf)

        # ── Step 6: Alerts ───────────────────────────────────────────────────
        if candles and scenarios:
            ts = candles[-1]["timestamp"]
            await alert_manager.process_scenarios(tf, scenarios, ts)


# ── Live Data Feed ──────────────────────────────────────────────────────────

def _fetch_from_api(tf: str) -> list:
    url = f"http://localhost:8000/api/ohlc?exchange=OANDA&symbol=EURUSD&timeframe={tf.lower()}&candles=200"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode('utf-8'))
                if body.get("status") == "success":
                    return body.get("candleData", [])
    except Exception as e:
        logger.error("API fetch failed for %s: %s", tf, e)
    return []

async def _live_feed_loop() -> None:
    """Continuously poll backend (dashboard chart source) and run engine cycle."""
    logger.info("Connecting engine to dashboard chart source (localhost:8000)...")
    while True:
        try:
            for tf in TIMEFRAMES:
                raw_candles = await asyncio.to_thread(_fetch_from_api, tf)
                for c in raw_candles:
                    t = c["time"]
                    if isinstance(t, (int, float)):
                        ts_ms = int(t * 1000)
                    else:
                        from datetime import datetime, timezone
                        try:
                            dt = datetime.strptime(str(t), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                            ts_ms = int(dt.timestamp() * 1000)
                        except Exception:
                            ts_ms = int(time.time() * 1000)

                    formatted = {
                        "timestamp": ts_ms,
                        "open": c["open"],
                        "high": c["high"],
                        "low": c["low"],
                        "close": c["close"],
                        "volume": 0,  # volume not strictly needed by engine, but could parse if present
                        "is_closed": True
                    }
                    fetcher_instance.add_candle(tf, formatted)
            
            await run_engine_cycle()
        except Exception as e:
            logger.error("Live feed loop error: %s", e)
        
        await asyncio.sleep(15)

# ── FastAPI lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def engine_lifespan(app):
    logger.info("=== Starting Multi-Timeframe Trading Intelligence Engine ===")
    task = asyncio.create_task(_live_feed_loop())
    logger.info("=== Engine live feed started ===")
    yield
    task.cancel()
    logger.info("=== Engine shutting down ===")


# Wire lifespan into the app
app.router.lifespan_context = engine_lifespan


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False, log_level="info")
