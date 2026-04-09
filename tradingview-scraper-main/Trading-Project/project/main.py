"""
Multi-Timeframe Engine — main entry point (optimized).

Changes:
  1. Uses modern FastAPI lifespan (replaces deprecated @app.on_event)
  2. Eliminates duplicate get_candles() calls per cycle (fetch once, reuse)
  3. Extracts consolidation zones per-timeframe and pushes them to the API
  4. Uses update_engine_output() for thread-safe state writes
  5. Mock feed produces more realistic data (directional trend with consolidation)
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from api.server import app, update_engine_output
from data.fetcher import fetcher_instance
from scenarios import generator
from confirmation import mtf
from alerts.manager import alert_manager
from strategy.consolidation import detect_consolidation

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

        # Extract consolidation zone for this TF (for the API /consolidations endpoint)
        consolidations_for_tf = []
        if len(candles) >= 5:
            zone = detect_consolidation(candles)
            if zone["valid"] and candles:
                ts_latest = candles[-1]["timestamp"]
                ts_start  = candles[max(0, len(candles) - 15)]["timestamp"]
                consolidations_for_tf = [{
                    "timeframe":  tf,
                    "priceHigh":  zone["high"],
                    "priceLow":   zone["low"],
                    "timeStart":  ts_start,
                    "timeEnd":    ts_latest,
                }]

        await update_engine_output(tf, scenarios, candles, consolidations_for_tf)

        # ── Step 6: Alerts ───────────────────────────────────────────────────
        if candles and scenarios:
            ts = candles[-1]["timestamp"]
            await alert_manager.process_scenarios(tf, scenarios, ts)


# ── Mock feed (used when no real data source is connected) ───────────────────

def _generate_mock_candles(n: int = 60) -> list:
    """
    Generates realistic mock EURUSD-like candles:
    - Rising trend for first 30 bars
    - Tight consolidation for next 20 bars
    - Breakout on bar 51+
    """
    import math, random
    now_ms = int(time.time() * 1000)
    candles = []
    price   = 1.08500

    for i in range(n):
        ts = now_ms - (n - i) * 60_000   # 1m bars
        # Trend phase
        if i < 30:
            drift = 0.00008 * math.sin(i * 0.2) + 0.000015
        # Consolidation phase
        elif i < 50:
            drift = random.uniform(-0.00005, 0.00005)
        # Breakout phase
        else:
            drift = 0.00020

        noise = random.gauss(0, 0.00004)
        open_p = price
        close  = round(price + drift + noise, 5)
        high   = round(max(open_p, close) + abs(random.gauss(0, 0.00008)), 5)
        low    = round(min(open_p, close) - abs(random.gauss(0, 0.00008)), 5)
        vol    = random.randint(800, 2500)

        candles.append({
            "timestamp": ts,
            "open":      open_p,
            "high":      high,
            "low":       low,
            "close":     close,
            "volume":    vol,
            "is_closed": True,
        })
        price = close

    return candles


async def _populate_mock_feed() -> None:
    """Seed all timeframes with synthetic candles so the engine has real data to work on."""
    logger.info("Seeding mock candle data for all timeframes…")
    mock = _generate_mock_candles(60)
    for tf in TIMEFRAMES:
        for candle in mock:
            fetcher_instance.add_candle(tf, candle)
    logger.info("Mock feed ready — %d candles per timeframe", len(mock))


# ── FastAPI lifespan (replaces deprecated @app.on_event) ────────────────────

@asynccontextmanager
async def engine_lifespan(app):
    logger.info("=== Starting Multi-Timeframe Trading Intelligence Engine ===")
    await _populate_mock_feed()
    await run_engine_cycle()   # Initial cycle on startup
    logger.info("=== Engine ready ===")
    yield
    logger.info("=== Engine shutting down ===")

# Wire lifespan into the app
app.router.lifespan_context = engine_lifespan


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False, log_level="info")
