from datetime import datetime
import pytz

def is_valid_time() -> bool:
    """Check if current time is between 11:00 and 22:00 IST."""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    return 11 <= now.hour < 22

def is_valid_timeframe(timeframe: str) -> bool:
    """Check if timeframe is allowed for alerts."""
    return timeframe in ["5m", "15m", "1H", "4H"]

def is_valid_event(scenario: dict) -> bool:
    """Check if the event is stringently breakout or trap."""
    name = scenario.get("scenario_name", "")
    return name in ["Continuation", "Trap Reversal"]
