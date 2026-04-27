import hashlib

symbol = "EURUSD"
tf = "1m"
ts = 1777049520000
target = "e34d5eef08891b37"

combinations = [
    f"{symbol}:{tf}:{ts}",
    f"OANDA:{symbol}:{tf}:{ts}",
    f"{tf}:{ts}",
    f"{symbol}:{ts}",
    f"{symbol}_{tf}_{ts}",
    f"{symbol}{tf}{ts}",
]

for c in combinations:
    h = hashlib.sha256(c.encode()).hexdigest()[:16]
    print(f"Key: {c} | Hash: {h} | Match: {h == target}")
