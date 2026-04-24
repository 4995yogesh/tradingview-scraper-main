"""
launcher_exe.py
Entry point for TradingDashboard.exe
- Serves React build on :3000
- Runs FastAPI backend on :8000 via uvicorn
- Logs errors to 'launcher.log' beside the .exe
"""
import os, sys, threading, webbrowser, time, traceback
import http.server, socketserver

# ── Log to file (windowed mode has no console) ────────────────────────────────
EXE_DIR = os.path.dirname(sys.executable)
LOG_PATH = os.path.join(EXE_DIR, "launcher.log")

def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

# ── Resource path (PyInstaller _MEIPASS) ─────────────────────────────────────
def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

_log(f"EXE_DIR={EXE_DIR}")
_log(f"_MEIPASS={getattr(sys, '_MEIPASS', 'NOT SET')}")

# ── Wire sys.path ─────────────────────────────────────────────────────────────
for p in [resource_path(),
          resource_path("backend"),
          resource_path("pipeline"),
          resource_path("project")]:
    if p not in sys.path:
        sys.path.insert(0, p)
    _log(f"sys.path += {p}  exists={os.path.isdir(p)}")

# ── Writable data dir beside .exe ────────────────────────────────────────────
DATA_DIR = os.path.join(EXE_DIR, "data")
os.makedirs(os.path.join(DATA_DIR, "models"), exist_ok=True)
os.environ["ML_DB_PATH"]     = os.path.join(DATA_DIR, "ml_feedback.db")
os.environ["CANDLE_DB_PATH"] = os.path.join(DATA_DIR, "candles.db")
_log(f"DATA_DIR={DATA_DIR}")

STATIC_DIR = resource_path("frontend_build")
_log(f"STATIC_DIR={STATIC_DIR}  exists={os.path.isdir(STATIC_DIR)}")

# ── React SPA static server ───────────────────────────────────────────────────
class _ReuseServer(socketserver.TCPServer):
    allow_reuse_address = True

class _SPAHandler(http.server.SimpleHTTPRequestHandler):
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
    try:
        _log("Starting static server on :3000")
        with _ReuseServer(("", 3000), _SPAHandler) as s:
            _log("Static server ready")
            s.serve_forever()
    except Exception:
        _log(f"Static server CRASHED:\n{traceback.format_exc()}")

# ── FastAPI backend ───────────────────────────────────────────────────────────
def _serve_backend():
    try:
        _log("Starting FastAPI backend on :8000")
        os.chdir(resource_path("backend"))
        import uvicorn
        from server import app
        _log("FastAPI app loaded, starting uvicorn")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    except Exception:
        _log(f"Backend CRASHED:\n{traceback.format_exc()}")

# ── Browser auto-open ─────────────────────────────────────────────────────────
def _open_browser():
    import urllib.request
    for i in range(120):
        try:
            urllib.request.urlopen("http://localhost:8000/api/health", timeout=1)
            _log("Backend healthy — opening browser")
            webbrowser.open("http://localhost:3000")
            return
        except Exception:
            time.sleep(0.5)
    _log("Browser open timeout — backend never responded")

if __name__ == "__main__":
    _log("=== TradingDashboard starting ===")
    threading.Thread(target=_serve_static, daemon=True).start()
    threading.Thread(target=_serve_backend, daemon=True).start()
    threading.Thread(target=_open_browser,  daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _log("Shutdown by user")
