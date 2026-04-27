import hashlib

symbol = "EURUSD"
tf = "1m"
ts_ms = 1777049520000
ts_s = 1777049520
target = "e34d5eef08891b37"

combinations = [
    f"{symbol}:{tf}:{ts_s}",
    f"OANDA:{symbol}:{tf}:{ts_s}",
    f"{tf}:{ts_s}",
    f"{symbol}:{ts_s}",
]

for c in combinations:
    h = hashlib.sha256(c.encode()).hexdigest()[:16]
    print(f"Key: {c} | Hash: {h} | Match: {h == target}")
