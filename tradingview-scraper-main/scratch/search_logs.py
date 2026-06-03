from pathlib import Path

log_path = Path("c:/Users/ysssi/Desktop/Tradingview_Main/launcher_debug.log")
if not log_path.exists():
    print(f"Log not found at {log_path}")
    exit(1)

print(f"Searching recent logs in {log_path}...")
lines_count = 0
matching_lines = []
with open(log_path, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        # Only interest in logs from the active session starting around 14:00
        if "2026-06-03 14:" in line:
            if any(k in line for k in ["gap-fill", "failed", "Dukascopy", "XAUUSD", "error", "exception"]):
                matching_lines.append(line.strip())

# Print the last 150 matching lines
for l in matching_lines[-150:]:
    print(l)
print(f"Done. Found {len(matching_lines)} matches in today's active session.")
