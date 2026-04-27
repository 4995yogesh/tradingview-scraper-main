import hashlib

expected = "e34d5eef08891b37"
sym = "EURUSD"
tf = "1m"
ts = 1777049520000
te = 1777051320000
ph = 1.17213
pl = 1.1717

def check(s):
    h = hashlib.sha256(s.encode()).hexdigest()[:16]
    if h == expected:
        print(f"MATCH: {s}")
        return True
    return False

# Try various combinations
seps = [":", "|", "-"]
t_formats = [
    (ts, te), 
    (ts // 1000, te // 1000), # seconds
    (ts, te, ph, pl),
    (ts // 1000, te // 1000, ph, pl)
]

for sep in seps:
    # sym:tf:ts
    check(f"{sym}{sep}{tf}{sep}{ts}")
    check(f"{sym}{sep}{tf}{sep}{ts//1000}")
    
    # sym:tf:ts:te
    check(f"{sym}{sep}{tf}{sep}{ts}{sep}{te}")
    check(f"{sym}{sep}{tf}{sep}{ts//1000}{sep}{te//1000}")
    
    # sym:tf:ts:te:ph:pl
    check(f"{sym}{sep}{tf}{sep}{ts}{sep}{te}{sep}{ph}{sep}{pl}")
    check(f"{sym}{sep}{tf}{sep}{ts//1000}{sep}{te//1000}{sep}{ph}{sep}{pl}")
    
    # With OANDA
    check(f"OANDA:{sym}{sep}{tf}{sep}{ts}")
    check(f"OANDA:{sym}{sep}{tf}{sep}{ts}{sep}{te}{sep}{ph}{sep}{pl}")

    # Maybe no tf?
    check(f"{sym}{sep}{ts}")
    
    # Maybe precision issues? Try .5f
    check(f"{sym}{sep}{tf}{sep}{ts}{sep}{te}{sep}{ph:.5f}{sep}{pl:.5f}")
    check(f"{sym}{sep}{tf}{sep}{ts//1000}{sep}{te//1000}{sep}{ph:.5f}{sep}{pl:.5f}")

print("Done.")
