"""
Dashboard Launcher — TradingView Scraper
=========================================
Starts two services:
  • Backend   (FastAPI) → http://localhost:8000
  • Frontend  (React)   → http://localhost:3000

Key improvements:
  - Window appears instantly (deferred init via root.after)
  - Browser only opens AFTER frontend is confirmed ready (HTTP poll)
  - "Open Canvas" button for manual open at any time
  - Proper yarn/npm detection with clear error messages
  - Port-free check before each start
  - Thread-safe log coloring (INFO / WARN / ERROR prefixes)
"""

import tkinter as tk
from tkinter import scrolledtext, ttk
import subprocess
import threading
import os
import sys
import shutil
import time
import webbrowser

try:
    import urllib.request as _urllib
    def _http_ok(url: str) -> bool:
        try:
            _urllib.urlopen(url, timeout=2)
            return True
        except Exception:
            return False
except ImportError:
    def _http_ok(url: str) -> bool:
        return False

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR     = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR  = os.path.join(ROOT_DIR, "Trading-Project", "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "Trading-Project", "frontend")   # React/CRACO
# Python executable (prefers .venv if present, else falls back to current interpreter)
PYTHON_EXEC = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON_EXEC):
    PYTHON_EXEC = sys.executable

# URLs
URL_BACKEND  = "http://localhost:8000/api/health"
URL_FRONTEND = "http://localhost:3000"
URL_CANVAS   = "http://localhost:3000/canvas"
URL_REFINE   = "http://localhost:3000/training"

# Colours (Dracula palette)
C_BG       = "#1e1e2e"
C_PANEL    = "#282a36"
C_FG       = "#f8f8f2"
C_GREEN    = "#50fa7b"
C_ORANGE   = "#ffb86c"
C_RED      = "#ff5555"
C_CYAN     = "#8be9fd"
C_PURPLE   = "#bd93f9"
C_YELLOW   = "#f1fa8c"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_node_exec(prefer_yarn: bool) -> str:
    """Return full path to yarn.cmd or npm.cmd, whichever is preferred + available."""
    candidates = (["yarn.cmd", "npm.cmd"] if prefer_yarn else ["npm.cmd", "yarn.cmd"])
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    # Last-ditch: just return the name and let the shell find it
    return candidates[0]


def _kill_pid(pid: int):
    subprocess.call(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _kill_port(port: int, log_fn=None):
    """Kill any process currently LISTENING on the given port."""
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
                    if log_fn:
                        log_fn(f"WARN  Killing PID {pid} on port {port}\n", C_ORANGE)
                    subprocess.call(
                        ["taskkill", "/F", "/PID", pid],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
    except Exception as exc:
        if log_fn:
            log_fn(f"ERROR  Port scan failed for {port}: {exc}\n", C_RED)


# ── Main Launcher class ───────────────────────────────────────────────────────

class DashboardLauncher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Trading Dashboard Launcher")
        self.root.geometry("900x650")
        self.root.configure(bg=C_BG)
        self.root.resizable(True, True)

        self.process_backend  = None
        self.process_frontend = None

        # Readiness poll stop events
        self._stop_backend_poll  = threading.Event()
        self._stop_frontend_poll = threading.Event()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Defer path checks + startup logs so window appears immediately
        self.root.after(10, self._deferred_init)

    # ── Deferred init (runs after mainloop starts) ───────────────────────────

    def _deferred_init(self):
        self._log("INFO  Launcher ready.\n", C_GREEN)
        self._log(f"INFO  PYTHON  → {PYTHON_EXEC}\n", C_CYAN)
        self._log(f"INFO  BACKEND → {BACKEND_DIR}\n", C_CYAN)
        self._log(f"INFO  FRONTEND→ {FRONTEND_DIR}\n", C_CYAN)
        for label, path in [("Backend dir", BACKEND_DIR), ("Frontend dir", FRONTEND_DIR)]:
            if not os.path.exists(path):
                self._log(f"ERROR  {label} NOT FOUND: {path}\n", C_RED)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton",
                         padding=6,
                         font=("Helvetica", 10, "bold"),
                         background=C_PANEL,
                         foreground=C_FG)
        style.map("TButton", background=[("active", "#44475a")])
        style.configure("TLabel", background=C_BG, foreground=C_FG, font=("Helvetica", 10))

        # ── Top control frame ─────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=C_BG)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=8)

        # Header
        tk.Label(top, text="Trading Dashboard Launcher",
                  bg=C_BG, fg=C_PURPLE,
                  font=("Helvetica", 14, "bold")).grid(
            row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))

        # Service rows
        services = [
            ("Backend  (port 8000)", 1, "backend"),
            ("Frontend (port 3000)", 2, "frontend"),
        ]

        self._status_labels = {}
        self._toggle_buttons = {}

        for (title, row, key) in services:
            tk.Label(top, text=title, bg=C_BG, fg=C_FG,
                      font=("Helvetica", 10)).grid(
                row=row, column=0, padx=8, pady=4, sticky=tk.W)

            lbl = tk.Label(top, text="● Stopped",
                            bg=C_BG, fg=C_ORANGE,
                            font=("Helvetica", 10, "bold"))
            lbl.grid(row=row, column=1, padx=8, pady=4, sticky=tk.W)
            self._status_labels[key] = lbl

            btn = ttk.Button(top, text=f"Start {title.split()[0]}",
                              command=lambda k=key: self._toggle(k))
            btn.grid(row=row, column=2, padx=8, pady=4)
            self._toggle_buttons[key] = btn

        # Start All / Stop All
        ttk.Button(top, text="▶  Start All",
                    command=self._start_all).grid(
            row=1, column=3, rowspan=2, padx=16, pady=4, sticky=tk.NSEW)

        ttk.Button(top, text="■  Stop All",
                    command=self._stop_all).grid(
            row=3, column=3, padx=16, pady=4, sticky=tk.NSEW)

        # ── Quick-open buttons ────────────────────────────────────────────────
        link_frame = tk.Frame(self.root, bg=C_BG)
        link_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=2)

        tk.Label(link_frame, text="Open in browser:", bg=C_BG, fg=C_FG,
                  font=("Helvetica", 10)).pack(side=tk.LEFT, padx=(0, 8))

        for (label, url, color) in [
            ("🔭 Canvas",       URL_CANVAS,           C_PURPLE),
            ("🎨 Refine Studio", URL_REFINE,           C_GREEN),
            ("📊 Dashboard",    URL_FRONTEND,          C_CYAN),
            ("⚙  Backend API", URL_BACKEND,            C_ORANGE),
        ]:
            tk.Button(link_frame, text=label,
                       bg=C_PANEL, fg=color,
                       font=("Helvetica", 9, "bold"),
                       relief=tk.FLAT, bd=0, padx=10, pady=4,
                       cursor="hand2",
                       command=lambda u=url: webbrowser.open(u)).pack(
                side=tk.LEFT, padx=4)

        # ── Log area ──────────────────────────────────────────────────────────
        self.log_area = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD,
            bg=C_PANEL, fg=C_FG,
            font=("Consolas", 9),
            insertbackground=C_FG,
        )
        self.log_area.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=12, pady=8)

        # Configure text tags for coloured log lines
        self.log_area.tag_config("green",  foreground=C_GREEN)
        self.log_area.tag_config("orange", foreground=C_ORANGE)
        self.log_area.tag_config("red",    foreground=C_RED)
        self.log_area.tag_config("cyan",   foreground=C_CYAN)
        self.log_area.tag_config("yellow", foreground=C_YELLOW)
        self.log_area.tag_config("purple", foreground=C_PURPLE)
        self.log_area.tag_config("default",foreground=C_FG)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, message: str, color: str = C_FG):
        tag = {
            C_GREEN: "green", C_ORANGE: "orange", C_RED: "red",
            C_CYAN: "cyan", C_YELLOW: "yellow", C_PURPLE: "purple",
        }.get(color, "default")
        self.log_area.insert(tk.END, message, tag)
        self.log_area.see(tk.END)

    def _log_ts(self, message: str, color: str = C_FG):
        ts = time.strftime("%H:%M:%S")
        self._log_safe(f"[{ts}] {message}", color)

    def _log_safe(self, message: str, color: str = C_FG):
        """Thread-safe log call via root.after."""
        self.root.after(0, self._log, message, color)

    def _read_output(self, process, prefix: str):
        """Stream subprocess stdout into the log window (runs in daemon thread)."""
        color_map = {
            "BACKEND": C_CYAN, "FRONTEND": C_GREEN,
            "INTEL": C_PURPLE, "ERROR": C_RED,
        }
        color = color_map.get(prefix, C_FG)
        try:
            for raw in iter(process.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace")
                # Highlight error lines regardless of prefix
                line_color = C_RED if ("error" in line.lower() or "exception" in line.lower()) else color
                self._log_safe(f"[{prefix}] {line}", line_color)
        except (ValueError, OSError):
            pass

    # ── Status label helpers ─────────────────────────────────────────────────

    def _set_status(self, key: str, running: bool, ready: bool = False):
        if ready:
            text, color = "● Ready", C_GREEN
        elif running:
            text, color = "◌ Starting…", C_YELLOW
        else:
            text, color = "● Stopped", C_ORANGE
        self.root.after(0, self._status_labels[key].config, {"text": text, "fg": color})

    # ── Readiness poll ────────────────────────────────────────────────────────

    def _poll_ready(self, url: str, key: str, stop_event: threading.Event,
                     open_browser_url: str = None, timeout_s: int = 120):
        """
        Poll `url` every 2 s until it returns HTTP 200 or timeout.
        Runs in a daemon thread — never blocks the UI.
        """
        deadline = time.time() + timeout_s
        while not stop_event.is_set() and time.time() < deadline:
            if _http_ok(url):
                self._set_status(key, running=True, ready=True)
                self._log_safe(f"INFO  {key.upper()} is ready at {url}\n", C_GREEN)
                if open_browser_url:
                    self._log_safe(f"INFO  Opening browser → {open_browser_url}\n", C_CYAN)
                    webbrowser.open(open_browser_url)
                return
            time.sleep(0.75)

        if not stop_event.is_set():
            self._log_safe(
                f"WARN  {key.upper()} did not become ready within {timeout_s}s.\n"
                f"      Check the log above for errors. You can still open it manually.\n",
                C_ORANGE,
            )

    # ── Port kill (with UI log) ───────────────────────────────────────────────

    def _kill_port(self, port: int):
        _kill_port(port, log_fn=self._log_ts)

    # ── Toggle dispatcher ────────────────────────────────────────────────────

    def _toggle(self, key: str):
        proc = getattr(self, f"process_{key}")
        if proc is None or proc.poll() is not None:
            getattr(self, f"_start_{key}")()
        else:
            getattr(self, f"_stop_{key}")()

    # ── Backend ───────────────────────────────────────────────────────────────

    def _start_backend(self):
        self._log_ts("Starting Backend (port 8000)…\n", C_CYAN)
        self._kill_port(8000)

        server_py = os.path.join(BACKEND_DIR, "server.py")
        if not os.path.exists(server_py):
            self._log_ts(f"ERROR  server.py not found: {server_py}\n", C_RED)
            return

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            self.process_backend = subprocess.Popen(
                [PYTHON_EXEC, "server.py"],
                cwd=BACKEND_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as exc:
            self._log_ts(f"ERROR  Failed to start backend: {exc}\n", C_RED)
            return

        threading.Thread(
            target=self._read_output,
            args=(self.process_backend, "BACKEND"),
            daemon=True,
        ).start()

        self._set_status("backend", running=True)
        self._toggle_buttons["backend"].config(text="Stop Backend")
        self._log_ts(f"INFO  Backend PID={self.process_backend.pid}\n", C_CYAN)

        # Start readiness poll — don't open browser automatically for backend-only start
        self._stop_backend_poll.clear()
        threading.Thread(
            target=self._poll_ready,
            args=(URL_BACKEND, "backend", self._stop_backend_poll),
            kwargs={"timeout_s": 60},
            daemon=True,
        ).start()

    def _stop_backend(self):
        self._log_ts("Stopping Backend…\n", C_ORANGE)
        self._stop_backend_poll.set()
        if self.process_backend:
            _kill_pid(self.process_backend.pid)
        self.process_backend = None
        self._set_status("backend", running=False)
        self._toggle_buttons["backend"].config(text="Start Backend")

    # ── Frontend ──────────────────────────────────────────────────────────────

    def _start_frontend(self):
        self._log_ts("Starting Frontend (port 3000)…\n", C_GREEN)
        self._kill_port(3000)

        if not os.path.exists(FRONTEND_DIR):
            self._log_ts(f"ERROR  Frontend directory not found: {FRONTEND_DIR}\n", C_RED)
            return

        has_yarn = os.path.exists(os.path.join(FRONTEND_DIR, "yarn.lock"))
        exec_path = _find_node_exec(prefer_yarn=has_yarn)
        full_cmd  = f'"{exec_path}" start'
        self._log_ts(f"INFO  Running: {full_cmd}  (cwd={FRONTEND_DIR})\n", C_GREEN)

        env = os.environ.copy()
        env["NODE_NO_WARNINGS"] = "1"
        env["NODE_OPTIONS"]     = "--no-deprecation"
        # Disable browser auto-open from CRA/CRACO — we handle it ourselves
        env["BROWSER"] = "none"

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            self.process_frontend = subprocess.Popen(
                full_cmd,
                cwd=FRONTEND_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                shell=True,
                env=env,
            )
        except Exception as exc:
            self._log_ts(f"ERROR  Failed to start frontend: {exc}\n", C_RED)
            return

        threading.Thread(
            target=self._read_output,
            args=(self.process_frontend, "FRONTEND"),
            daemon=True,
        ).start()

        self._set_status("frontend", running=True)
        self._toggle_buttons["frontend"].config(text="Stop Frontend")
        self._log_ts(
            f"INFO  Frontend PID={self.process_frontend.pid} — "
            f"polling for readiness (may take 30–60 s)…\n",
            C_GREEN,
        )

        # Poll for readiness, then open chart (localhost:3000)
        self._stop_frontend_poll.clear()
        threading.Thread(
            target=self._poll_ready,
            args=(URL_FRONTEND, "frontend", self._stop_frontend_poll, URL_FRONTEND),
            kwargs={"timeout_s": 120},
            daemon=True,
        ).start()

    def _stop_frontend(self):
        self._log_ts("Stopping Frontend…\n", C_ORANGE)
        self._stop_frontend_poll.set()
        if self.process_frontend:
            _kill_pid(self.process_frontend.pid)
        self.process_frontend = None
        self._set_status("frontend", running=False)
        self._toggle_buttons["frontend"].config(text="Start Frontend")

    # ── Start All / Stop All ──────────────────────────────────────────────────

    def _start_all(self):
        """Start Backend + Frontend in parallel — frontend compile overlaps with backend init."""
        def _start_backend_and_wait():
            if self.process_backend is None or self.process_backend.poll() is not None:
                self.root.after(0, self._start_backend)
            self._log_ts("Waiting for backend to become ready...\n", C_YELLOW)
            for _ in range(60):   # max 30s (60 × 0.5s)
                if _http_ok(URL_BACKEND):
                    self._log_ts("INFO  Backend ready.\n", C_GREEN)
                    return
                time.sleep(0.5)
            self._log_ts("WARN  Backend startup timeout, continuing...\n", C_ORANGE)

        def _start_frontend_and_wait():
            if self.process_frontend is None or self.process_frontend.poll() is not None:
                self.root.after(0, self._start_frontend)
            self._log_ts("Waiting for frontend to become ready...\n", C_YELLOW)
            for _ in range(180):  # max 90s (180 × 0.5s)
                if _http_ok(URL_FRONTEND):
                    self._log_ts("INFO  Frontend ready.\n", C_GREEN)
                    return
                time.sleep(0.5)
            self._log_ts("WARN  Frontend startup timeout, continuing...\n", C_ORANGE)

        def _seq():
            # Launch both in parallel — frontend compile has no backend dependency
            t_be = threading.Thread(target=_start_backend_and_wait, daemon=True)
            t_fe = threading.Thread(target=_start_frontend_and_wait, daemon=True)
            t_be.start()
            t_fe.start()
            t_be.join()
            t_fe.join()

        threading.Thread(target=_seq, daemon=True).start()

    def _stop_all(self):
        self._log_ts("Stopping all services…\n", C_ORANGE)
        for key in ("backend", "frontend"):
            proc = getattr(self, f"process_{key}")
            if proc is not None and proc.poll() is None:
                getattr(self, f"_stop_{key}")()

    # ── Window close ─────────────────────────────────────────────────────────

    def _on_close(self):
        self._log_ts("Shutting down…\n", C_RED)
        self.root.title("Shutting down...")
        self.root.after(10, lambda: [self._stop_all(), self.root.destroy()])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app  = DashboardLauncher(root)
    if "--auto" in sys.argv:
        root.after(50, app._start_all)  # defer until window is fully visible
    root.mainloop()
