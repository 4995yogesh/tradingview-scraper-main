"""
build_exe.py
============
Build a standalone TradingDashboard.exe that:
  1. Builds the React frontend (yarn build / npm build)
  2. Packages backend + static frontend with PyInstaller

Run:
    python build_exe.py

Output:
    dist/TradingDashboard/TradingDashboard.exe
    (distribute the entire dist/TradingDashboard folder)
"""

import os
import sys
import shutil
import subprocess
import platform

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT_DIR     = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR  = os.path.join(ROOT_DIR, "Trading-Project", "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "frontend")
PIPELINE_DIR = os.path.join(ROOT_DIR, "Trading-Project", "pipeline")
PROJECT_DIR  = os.path.join(ROOT_DIR, "Trading-Project", "project")
DATA_DIR     = os.path.join(ROOT_DIR, "Trading-Project", "data")
BUILD_DIR    = os.path.join(ROOT_DIR, "build_output")
DIST_DIR     = os.path.join(ROOT_DIR, "dist")
ICON_PATH    = os.path.join(FRONTEND_DIR, "public", "favicon.ico")
ENTRY_SCRIPT = os.path.join(ROOT_DIR, "launcher_exe.py")

print(f"[build] ROOT_DIR  = {ROOT_DIR}")
print(f"[build] BACKEND   = {BACKEND_DIR}")
print(f"[build] FRONTEND  = {FRONTEND_DIR}")

# ── Step 1: Build React frontend ───────────────────────────────────────────────
print("\n[build] Step 1: Building React frontend...")

has_yarn = os.path.exists(os.path.join(FRONTEND_DIR, "yarn.lock"))
pkg_mgr  = shutil.which("yarn") or shutil.which("yarn.cmd")
if not has_yarn or not pkg_mgr:
    pkg_mgr = shutil.which("npm") or shutil.which("npm.cmd") or "npm"

print(f"[build] Package manager: {pkg_mgr}")

result = subprocess.run(
    [pkg_mgr, "run", "build"],
    cwd=FRONTEND_DIR,
    check=False
)
if result.returncode != 0:
    print("[build] ERROR: Frontend build failed.")
    sys.exit(1)

STATIC_DIR = os.path.join(FRONTEND_DIR, "build")
if not os.path.exists(STATIC_DIR):
    print(f"[build] ERROR: Expected build output at {STATIC_DIR}")
    sys.exit(1)

print(f"[build] Frontend built at: {STATIC_DIR}")

# ── Step 2: Install PyInstaller ────────────────────────────────────────────────
print("\n[build] Step 2: Checking PyInstaller...")
try:
    import PyInstaller  # noqa: F401
except ImportError:
    print("[build] Installing PyInstaller...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

# ── Step 3: Write launcher_exe.py ─────────────────────────────────────────────
print("\n[build] Step 3: Writing launcher_exe.py...")

launcher_code = '''"""
launcher_exe.py
Entry point for the packaged .exe.
- Serves the React build on :3000 (static file server)
- Runs FastAPI backend on :8000 (uvicorn in-process)
- Opens the browser automatically when the backend is ready
"""
import os, sys, threading, webbrowser, time
import http.server, socketserver

def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

# ── Wire sys.path ──────────────────────────────────────────────────────────────
for p in [resource_path(), resource_path("backend"),
          resource_path("pipeline"), resource_path("project")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Data directory (writable, beside the .exe) ────────────────────────────────
EXE_DIR  = os.path.dirname(sys.executable if hasattr(sys, "_MEIPASS") else os.path.abspath(__file__))
DATA_DIR = os.path.join(EXE_DIR, "data")
os.makedirs(os.path.join(DATA_DIR, "models"), exist_ok=True)
os.environ["ML_DB_PATH"]     = os.path.join(DATA_DIR, "ml_feedback.db")
os.environ["CANDLE_DB_PATH"] = os.path.join(DATA_DIR, "candles.db")

STATIC_DIR = resource_path("frontend_build")

# ── React SPA static server ───────────────────────────────────────────────────
class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC_DIR, **kw)
    def do_GET(self):
        clean = self.path.split("?")[0].split("#")[0]
        fpath = os.path.join(STATIC_DIR, clean.lstrip("/"))
        if os.path.isfile(fpath):
            super().do_GET()
        else:
            self.path = "/index.html"
            super().do_GET()
    def log_message(self, *a):
        pass

def _serve_static():
    with socketserver.TCPServer(("", 3000), SPAHandler) as s:
        s.allow_reuse_address = True
        s.serve_forever()

# ── FastAPI backend ────────────────────────────────────────────────────────────
def _serve_backend():
    import uvicorn
    from server import app
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

# ── Browser auto-open ─────────────────────────────────────────────────────────
def _open_browser():
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen("http://localhost:8000/api/health", timeout=5)
            webbrowser.open("http://localhost:3000")
            return
        except Exception:
            time.sleep(0.5)

if __name__ == "__main__":
    threading.Thread(target=_serve_static, daemon=True).start()
    threading.Thread(target=_serve_backend, daemon=True).start()
    threading.Thread(target=_open_browser,  daemon=True).start()
    print("Trading Dashboard running. Close this window to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
'''

with open(ENTRY_SCRIPT, "w", encoding="utf-8") as f:
    f.write(launcher_code)
print(f"[build] Written: {ENTRY_SCRIPT}")

# ── Step 4: Assemble PyInstaller args ─────────────────────────────────────────
print("\n[build] Step 4: Assembling PyInstaller command...")

sep = ";" if platform.system() == "Windows" else ":"

add_data = [
    f"{BACKEND_DIR}{sep}backend",
    f"{PIPELINE_DIR}{sep}pipeline",
    f"{PROJECT_DIR}{sep}project",
    f"{STATIC_DIR}{sep}frontend_build",
]

tv_pkg = os.path.join(ROOT_DIR, "tradingview_scraper")
if os.path.isdir(tv_pkg):
    add_data.append(f"{tv_pkg}{sep}tradingview_scraper")

hidden_imports = [
    "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "fastapi", "fastapi.middleware.cors",
    "starlette", "starlette.staticfiles",
    "pydantic", "pydantic.v1",
    "lightgbm", "lightgbm.sklearn",
    "pandas", "numpy", "scipy",
    "aiofiles", "dotenv", "httpx",
    "sqlite3", "websocket", "websockets",
    "tradingview_scraper",
    "concurrent.futures",
    "multiprocessing",
]

cmd = [
    sys.executable, "-m", "PyInstaller",
    ENTRY_SCRIPT,
    "--name", "TradingDashboard",
    "--onedir",
    "--windowed",
    "--noconfirm",
    "--distpath", DIST_DIR,
    "--workpath", BUILD_DIR,
    "--specpath", ROOT_DIR,
]

if os.path.exists(ICON_PATH):
    cmd += ["--icon", ICON_PATH]

for hi in hidden_imports:
    cmd += ["--hidden-import", hi]

for ad in add_data:
    cmd += ["--add-data", ad]

# ── Step 5: Run PyInstaller ────────────────────────────────────────────────────
print("\n[build] Step 5: Running PyInstaller (this may take 2-5 minutes)...")
print("[build] Command:", " ".join(cmd[:6]), "... (truncated)")

result = subprocess.run(cmd, check=False)

if result.returncode != 0:
    print("\n[build] FAILED. See output above.")
    sys.exit(1)

EXE_PATH = os.path.join(DIST_DIR, "TradingDashboard", "TradingDashboard.exe")
print(f"\n[build] SUCCESS!")
print(f"[build] Exe: {EXE_PATH}")
print(f"[build] Distribute the entire 'dist/TradingDashboard/' folder.")
print(f"[build] The 'data/' folder next to the .exe persists your database.")
