import sys
import re

file_path = 'c:/Users/ysssi/Downloads/Compressed/tradingview-scraper-main/tradingview-scraper-main/Trading-Project/backend/server.py'

with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

get_ohlc_new = """@app.get("/api/ohlc")
def get_ohlc(
    exchange: str = Query("OANDA"),
    symbol:   str = Query("EURUSD"),
    timeframe: str = Query("1d"),
    candles:  int = Query(500, ge=10, le=100000),
    end_time: Optional[str] = Query(None),
):
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Unsupported timeframe '{timeframe}'. Choose from: {list(TIMEFRAME_MAP)}")

    if ":" in symbol:
        exchange, symbol = symbol.split(":", 1)

    parsed_end = parse_end_time(end_time)
    logger.info("OHLC (DB-First) → %s:%s tf=%s candles=%d end=%s", exchange, symbol, timeframe, candles, end_time)
    
    is_recent = end_time is None

    # 1. Fetch CLOSED candles strictly from SQLite Database
    closed_candles = candle_db.get_candles(exchange, symbol, timeframe, count=candles, end_ts=parsed_end)
    
    # 2. Bridge Live HTF Segment using 1m DB & RAM partials
    if is_recent and timeframe != "1m" and closed_candles:
        latest_closed_ts = int(float(closed_candles[-1].get("ts", closed_candles[-1].get("time", 0))))
        tf_secs = TF_INTERVAL_SECS.get(timeframe, 60)
        unclosed_boundary = latest_closed_ts + tf_secs
        
        # Pull any closed 1m segments bridging the gap out of DB securely
        live_1m = candle_db.get_candles(exchange, symbol, "1m", count=4000, start_ts=unclosed_boundary)
        
        # Extract purely unclosed live 1m tick from RAM cache
        latest_1m_ram = storage.get_candles(exchange, symbol, "1m", count=5)
        ram_ticks = []
        for c in latest_1m_ram:
            ts = int(float(c.get("timestamp", c.get("ts", c.get("time", 0)))))
            if ts >= unclosed_boundary:
                ram_ticks.append(c)
                
        # Consolidate arrays
        unclosed_ticks = live_1m + ram_ticks
        if unclosed_ticks:
            bridge = resample_candles(unclosed_ticks, timeframe)
            if bridge:
                closed_candles.append(bridge[0])

    elif timeframe == "1m" and is_recent and closed_candles:
        # 1m just appends its active floating tick cleanly
        ram_ticks = storage.get_candles(exchange, symbol, "1m", count=1)
        if ram_ticks:
            closed_candles.append(ram_ticks[-1])

    cd, vd = _format_candles_for_ui(closed_candles, timeframe)
    return {"status": "success", "candleData": cd, "volumeData": vd}

"""

# find start and end
pattern = re.compile(r'@app\.get\("/api/ohlc"\)\s*\ndef get_ohlc\(.*?(?=@app\.get\("/api/consolidation"\))', re.DOTALL)
new_text, count = pattern.subn(get_ohlc_new, text)

if count > 0:
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Successfully replaced get_ohlc")
else:
    print("Failed to match get_ohlc pattern")
