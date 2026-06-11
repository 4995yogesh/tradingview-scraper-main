import asyncio
import os
import subprocess
import sys
import threading
import shutil
import urllib.request
import webbrowser
from typing import Dict, Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

# ── Globals ───────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "frontend")

PYTHON_EXEC = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXEC):
    PYTHON_EXEC = sys.executable

processes: Dict[str, Optional[subprocess.Popen]] = {
    "backend": None,
    "frontend": None,
}

app = FastAPI()

# ── Logging System ────────────────────────────────────────────────────────────
active_connections: List[WebSocket] = []
log_queue = asyncio.Queue()
main_loop = None

async def log_broadcaster():
    while True:
        msg, color = await log_queue.get()
        data = {"text": msg, "color": color}
        to_remove = []
        for connection in active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                to_remove.append(connection)
        for conn in to_remove:
            if conn in active_connections:
                active_connections.remove(conn)

def queue_log(msg: str, color: str = "#f8f8f2"):
    print(msg, end="") # also print to main console
    if main_loop and main_loop.is_running():
        main_loop.call_soon_threadsafe(log_queue.put_nowait, (msg, color))

@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()
    asyncio.create_task(log_broadcaster())
    
    queue_log("[INFO] Web Launcher ready on http://localhost:8001\n", "#50fa7b")
    # Auto-open browser
    webbrowser.open("http://localhost:8001")

# ── Helpers ───────────────────────────────────────────────────────────────────
def _find_node_exec(prefer_yarn: bool) -> str:
    candidates = (["yarn.cmd", "npm.cmd"] if prefer_yarn else ["npm.cmd", "yarn.cmd"])
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return candidates[0]

def _kill_port(port: int):
    try:
        result = subprocess.run(
            f"netstat -ano | findstr LISTENING | findstr :{port}",
            shell=True, capture_output=True, text=True,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}"):
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0:
                    queue_log(f"[WARN] Killing PID {pid} on port {port}\n", "#ffb86c")
                    subprocess.call(["taskkill", "/F", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        queue_log(f"[ERROR] Port scan failed for {port}: {exc}\n", "#ff5555")

def _kill_pid(pid: int):
    subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def check_http(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=5)
        return True
    except Exception:
        return False

# ── Process Output Reader ─────────────────────────────────────────────────────
def read_output(process, prefix: str):
    color_map = {
        "BACKEND": "#8be9fd", "FRONTEND": "#50fa7b", "ERROR": "#ff5555"
    }
    color = color_map.get(prefix, "#f8f8f2")
    try:
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace")
            line_color = "#ff5555" if ("error" in line.lower() or "exception" in line.lower()) else color
            queue_log(f"[{prefix}] {line}", line_color)
    except (ValueError, OSError):
        pass

# ── Process Control ───────────────────────────────────────────────────────────
def start_backend_process():
    if processes["backend"] and processes["backend"].poll() is None:
        return
    queue_log("[INFO] Starting Backend (port 8000)...\n", "#8be9fd")
    _kill_port(8000)
    server_py = os.path.join(BACKEND_DIR, "server.py")
    if not os.path.exists(server_py):
        queue_log(f"[ERROR] server.py not found: {server_py}\n", "#ff5555")
        return

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.Popen(
        [PYTHON_EXEC, "server.py"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    processes["backend"] = proc
    threading.Thread(target=read_output, args=(proc, "BACKEND"), daemon=True).start()

def stop_backend_process():
    proc = processes["backend"]
    if proc:
        _kill_pid(proc.pid)
        processes["backend"] = None
        queue_log("[INFO] Backend stopped.\n", "#ffb86c")

def start_frontend_process():
    if processes["frontend"] and processes["frontend"].poll() is None:
        return
    queue_log("[INFO] Starting Frontend (port 3000)...\n", "#50fa7b")
    _kill_port(3000)

    if not os.path.exists(FRONTEND_DIR):
        queue_log(f"[ERROR] Frontend directory not found: {FRONTEND_DIR}\n", "#ff5555")
        return

    has_yarn = os.path.exists(os.path.join(FRONTEND_DIR, "yarn.lock"))
    exec_path = _find_node_exec(prefer_yarn=has_yarn)
    full_cmd = f'"{exec_path}" start'

    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    env["NODE_OPTIONS"] = "--no-deprecation"
    env["BROWSER"] = "none"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.Popen(
        full_cmd,
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        shell=True,
        env=env,
    )
    processes["frontend"] = proc
    threading.Thread(target=read_output, args=(proc, "FRONTEND"), daemon=True).start()

def stop_frontend_process():
    proc = processes["frontend"]
    if proc:
        _kill_pid(proc.pid)
        processes["frontend"] = None
        queue_log("[INFO] Frontend stopped.\n", "#ffb86c")

# ── API Endpoints ─────────────────────────────────────────────────────────────
@app.post("/api/start_all")
def start_all():
    start_backend_process()
    start_frontend_process()
    return {"status": "started"}

@app.post("/api/stop_all")
def stop_all():
    stop_backend_process()
    stop_frontend_process()
    return {"status": "stopped"}

@app.post("/api/start/{service}")
def start_service(service: str):
    if service == "backend": start_backend_process()
    elif service == "frontend": start_frontend_process()
    return {"status": "started"}

@app.post("/api/stop/{service}")
def stop_service(service: str):
    if service == "backend": stop_backend_process()
    elif service == "frontend": stop_frontend_process()
    return {"status": "stopped"}

@app.get("/api/status")
def get_status():
    backend_running = processes["backend"] is not None and processes["backend"].poll() is None
    frontend_running = processes["frontend"] is not None and processes["frontend"].poll() is None
    
    backend_ready = check_http("http://localhost:8000/api/health") if backend_running else False
    frontend_ready = check_http("http://localhost:3000") if frontend_running else False
    
    return {
        "backend": {"running": backend_running, "ready": backend_ready},
        "frontend": {"running": frontend_running, "ready": frontend_ready}
    }

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text() # keep connection open
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)

# ── HTML Template ─────────────────────────────────────────────────────────────
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Trading Dashboard Launcher</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #1e1e2e; color: #f8f8f2; font-family: 'Inter', sans-serif; }
        .glass-panel { background: #282a36; border: 1px solid #44475a; border-radius: 12px; }
        .log-container { background: #191a21; overflow-y: auto; font-family: 'Consolas', monospace; font-size: 13px; }
        .btn-purple { background: #bd93f9; color: #282a36; }
        .btn-purple:hover { background: #caa9fa; }
        .btn-red { background: #ff5555; color: #282a36; }
        .btn-red:hover { background: #ff6e6e; }
        .btn-green { background: #50fa7b; color: #282a36; }
        .btn-green:hover { background: #69ff94; }
        .status-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
        .status-stopped { background: #ffb86c; }
        .status-starting { background: #f1fa8c; }
        .status-ready { background: #50fa7b; }
        .status-shadow { box-shadow: 0 0 8px currentColor; }
    </style>
</head>
<body class="p-8 h-screen flex flex-col overflow-hidden">
    <div class="max-w-6xl mx-auto w-full flex-1 flex flex-col space-y-6 min-h-0">
        
        <div class="flex justify-between items-center flex-shrink-0">
            <h1 class="text-3xl font-bold text-[#bd93f9]">Trading Dashboard Launcher</h1>
            <div class="space-x-3">
                <button onclick="apiCall('/api/start_all')" class="btn-green px-6 py-2 rounded-lg font-bold shadow-lg transition">▶ Start All</button>
                <button onclick="apiCall('/api/stop_all')" class="btn-red px-6 py-2 rounded-lg font-bold shadow-lg transition">■ Stop All</button>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-6 flex-shrink-0">
            <!-- Backend Panel -->
            <div class="glass-panel p-6 flex flex-col space-y-4">
                <div class="flex justify-between items-center">
                    <h2 class="text-xl font-semibold text-[#8be9fd]">Backend Service <span class="text-xs text-gray-500 font-normal ml-2">(port 8000)</span></h2>
                    <span class="flex items-center space-x-2">
                        <span id="backend-dot" class="status-dot status-stopped"></span>
                        <span id="backend-text" class="text-sm font-bold text-[#ffb86c]">Stopped</span>
                    </span>
                </div>
                <div class="flex space-x-3">
                    <button id="backend-btn" onclick="toggleService('backend')" class="bg-[#44475a] hover:bg-[#6272a4] px-4 py-2 rounded-md font-medium transition w-32">Start</button>
                    <button onclick="window.open('http://localhost:8000/docs', '_blank')" class="bg-[#44475a] hover:bg-[#6272a4] px-4 py-2 rounded-md font-medium transition text-[#ffb86c]">⚙ API Docs</button>
                </div>
            </div>

            <!-- Frontend Panel -->
            <div class="glass-panel p-6 flex flex-col space-y-4">
                <div class="flex justify-between items-center">
                    <h2 class="text-xl font-semibold text-[#50fa7b]">Frontend Service <span class="text-xs text-gray-500 font-normal ml-2">(port 3000)</span></h2>
                    <span class="flex items-center space-x-2">
                        <span id="frontend-dot" class="status-dot status-stopped"></span>
                        <span id="frontend-text" class="text-sm font-bold text-[#ffb86c]">Stopped</span>
                    </span>
                </div>
                <div class="flex space-x-3">
                    <button id="frontend-btn" onclick="toggleService('frontend')" class="bg-[#44475a] hover:bg-[#6272a4] px-4 py-2 rounded-md font-medium transition w-32">Start</button>
                    <button onclick="window.open('http://localhost:3000', '_blank')" class="bg-[#44475a] hover:bg-[#6272a4] px-4 py-2 rounded-md font-medium transition text-[#8be9fd]">📊 Dashboard</button>
                    <button onclick="window.open('http://localhost:3000/canvas', '_blank')" class="bg-[#44475a] hover:bg-[#6272a4] px-4 py-2 rounded-md font-medium transition text-[#bd93f9]">🔭 Canvas</button>
                    <button onclick="window.open('http://localhost:3000/training', '_blank')" class="bg-[#44475a] hover:bg-[#6272a4] px-4 py-2 rounded-md font-medium transition text-[#50fa7b]">🎨 Refine</button>
                </div>
            </div>
        </div>

        <div class="glass-panel flex-1 flex flex-col overflow-hidden min-h-0">
            <div class="px-4 py-2 bg-[#1e1e2e] border-b border-[#44475a] font-mono text-sm text-[#6272a4] flex justify-between items-center flex-shrink-0">
                <span>Terminal Output</span>
                <button onclick="document.getElementById('logs').innerHTML=''" class="hover:text-white transition">Clear</button>
            </div>
            <div id="logs" class="log-container p-4 flex-1 whitespace-pre-wrap overflow-y-auto min-h-0"></div>
        </div>
    </div>

    <script>
        // State
        let services = {
            backend: { running: false, ready: false },
            frontend: { running: false, ready: false }
        };

        // API Calls
        async function apiCall(endpoint) {
            await fetch(endpoint, { method: 'POST' });
            pollStatus();
        }

        function toggleService(service) {
            if (services[service].running) {
                apiCall(`/api/stop/${service}`);
            } else {
                apiCall(`/api/start/${service}`);
            }
        }

        // Status Polling
        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                services = data;
                updateUI();
            } catch (e) {
                console.error("Failed to fetch status");
            }
        }

        function updateUI() {
            ['backend', 'frontend'].forEach(srv => {
                const state = services[srv];
                const dot = document.getElementById(`${srv}-dot`);
                const text = document.getElementById(`${srv}-text`);
                const btn = document.getElementById(`${srv}-btn`);
                
                if (state.ready) {
                    dot.className = "status-dot status-ready status-shadow text-[#50fa7b]";
                    text.textContent = "Ready";
                    text.className = "text-sm font-bold text-[#50fa7b]";
                    btn.textContent = "Stop";
                } else if (state.running) {
                    dot.className = "status-dot status-starting status-shadow text-[#f1fa8c]";
                    text.textContent = "Starting...";
                    text.className = "text-sm font-bold text-[#f1fa8c]";
                    btn.textContent = "Stop";
                } else {
                    dot.className = "status-dot status-stopped text-[#ffb86c]";
                    text.textContent = "Stopped";
                    text.className = "text-sm font-bold text-[#ffb86c]";
                    btn.textContent = "Start";
                }
            });
        }

        setInterval(pollStatus, 1000);
        pollStatus();

        // WebSocket Logs
        function connectWS() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//${window.location.host}/ws/logs`);
            const logDiv = document.getElementById('logs');
            let isAtBottom = true;
            
            logDiv.addEventListener('scroll', () => {
                isAtBottom = Math.abs((logDiv.scrollHeight - logDiv.scrollTop) - logDiv.clientHeight) < 10;
            });

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const span = document.createElement('span');
                span.style.color = data.color;
                span.textContent = data.text;
                logDiv.appendChild(span);
                
                // Keep max 2000 elements to prevent lag
                if (logDiv.childNodes.length > 2000) {
                    for(let i=0; i<500; i++) logDiv.removeChild(logDiv.firstChild);
                }
                
                // Auto scroll if user hasn't scrolled up
                if (isAtBottom) {
                    logDiv.scrollTop = logDiv.scrollHeight;
                }
            };
            
            ws.onclose = () => setTimeout(connectWS, 2000);
        }
        connectWS();
    </script>
</body>
</html>
"""

@app.get("/")
def get_index():
    return HTMLResponse(content=HTML_CONTENT)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
