"""
Fix cookie_value line in server.py — replaces os.getenv with _TV_COOKIE.
"""
path = "Trading-Project/backend/server.py"
with open(path, encoding="utf-8") as f:
    content = f.read()

old = '        cookie_value = os.getenv("TRADINGVIEW_COOKIE", "").strip()\n'
new = '        cookie_value = _TV_COOKIE   # auto-extracted from browser store at startup\n'

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: replaced cookie_value line")
else:
    # Try with \r\n
    old_rn = old.replace("\n", "\r\n")
    new_rn = new.replace("\n", "\r\n")
    if old_rn in content:
        content = content.replace(old_rn, new_rn, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("OK (CRLF): replaced cookie_value line")
    else:
        # Find surrounding context
        idx = content.find("cookie_value = os")
        print(f"NOT FOUND. Nearest match at {idx}:")
        print(repr(content[idx:idx+120]) if idx >= 0 else "not found at all")
