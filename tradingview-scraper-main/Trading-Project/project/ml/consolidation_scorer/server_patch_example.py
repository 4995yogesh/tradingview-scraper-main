"""
server_patch_example.py
=======================
Shows how to integrate the ConsolidationScorer into the existing FastAPI backend.
Copy the relevant blocks into server.py.

CHANGES REQUIRED IN server.py:
  1. Import scorer at top (after existing imports)
  2. Load scorer in lifespan
  3. Add /api/consolidation/scored endpoint
"""

# ── (1) Add near top of server.py (after existing imports) ───────────────────
# from ml.consolidation_scorer.scorer import ConsolidationScorer
# _scorer: ConsolidationScorer = None

# ── (2) Inside lifespan(), after pipeline.start() ────────────────────────────
# global _scorer
# try:
#     from ml.consolidation_scorer.scorer import ConsolidationScorer
#     _scorer = ConsolidationScorer()
#     logger.info("ConsolidationScorer loaded — ready=%s", _scorer.ready)
# except Exception as e:
#     logger.warning("ConsolidationScorer not available: %s", e)
#     _scorer = None

# ── (3) New endpoint (add below existing /api/consolidation endpoint) ─────────

# @app.get("/api/consolidation/scored")
# def get_consolidation_scored(
#     exchange:  str   = Query("OANDA"),
#     symbol:    str   = Query("EURUSD"),
#     timeframe: str   = Query("1h"),
#     candles:   int   = Query(500, ge=10, le=100000),
#     threshold: float = Query(0.0, ge=0.0, le=1.0),
# ):
#     """
#     Return consolidation boxes enriched with ML quality scores [0,1].
#     Optionally filter by threshold.
#     """
#     use_timestamp = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
#     stored = storage.get_candles(exchange, symbol, timeframe, count=candles)
#     if not stored:
#         raise HTTPException(404, "No candle data available")
#
#     df = pd.DataFrame(stored)
#     if use_timestamp:
#         df.index = pd.to_datetime(df["time"], unit="s", utc=True)
#     else:
#         df.index = pd.to_datetime(df["time"])
#     df = df[["open", "high", "low", "close"]].astype(float)
#
#     boxes = consolidation_boxes(df, min_bars=5, use_time_filter=False)
#     if boxes.empty:
#         return {"status": "success", "boxes": []}
#
#     if _scorer and _scorer.ready:
#         scored = _scorer.score(df, boxes, threshold=threshold)
#     else:
#         scored = boxes.copy()
#         scored["quality"]       = 0.5
#         scored["quality_color"] = "#FFB86C"
#
#     # Convert timestamps for JSON
#     scored["start_time"] = df.index[scored["start"].astype(int)].astype(str).values
#     scored["end_time"]   = df.index[scored["end"].astype(int)].astype(str).values
#
#     return {
#         "status": "success",
#         "scorer_ready": _scorer.ready if _scorer else False,
#         "boxes": scored.to_dict(orient="records"),
#     }
