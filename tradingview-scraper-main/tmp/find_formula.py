import hashlib

data = [
    ("e34d5eef08891b37", "EURUSD", "1m", 1777049520000),
    ("b2df46769fc3e97a", "EURUSD", "1m", 1777049040000),
]

def test_formula(f):
    for expected, sym, tf, ts in data:
        key = f(sym, tf, ts)
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        if h != expected:
            return False
    return True

formulas = [
    lambda sym, tf, ts: f"{sym}:{tf}:{ts}",
    lambda sym, tf, ts: f"{sym}:{tf}:{int(ts)}",
    lambda sym, tf, ts: f"{tf}:{ts}",
    lambda sym, tf, ts: f"{sym}:{tf}:{ts // 1000}",
    
    # Maybe zone['timeStart'] is stored differently?
    lambda sym, tf, ts: f"{sym}:{tf}:{ts / 1000.0}",
    lambda sym, tf, ts: f"{sym}:{tf}:{int(ts / 1000)}",
]

for i, f in enumerate(formulas):
    if test_formula(f):
        print(f"Match found: Formula {i}")
        expected, sym, tf, ts = data[0]
        print(f"Key used: {f(sym, tf, ts)}")
        break
else:
    print("No matches found for 1m data.")
