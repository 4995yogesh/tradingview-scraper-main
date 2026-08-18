"""Start the complete local market/research workspace and open one dashboard.

Run from Trading-Project:

    python start_research_dashboard.py

The launcher starts:
1. FastAPI backend on http://127.0.0.1:8000
2. Existing React chart frontend on http://127.0.0.1:3000
3. Browser at http://127.0.0.1:3000/research

It does not duplicate either application; it only orchestrates the existing entrypoints.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
BACKEND_HEALTH = "http://127.0.0.1:8000/api/health"
FRONTEND_URL = "http://127.0.0.1:3000/research"


def _command_exists(name: str) -> str | None:
    return shutil.which(name)


def _http_ready(url: str, timeout: float = 0.7) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:  # nosec B310 - localhost only
            return 200 <= response.status < 500
    except (URLError, OSError, TimeoutError):
        return False


def _wait_until_ready(url: str, process: subprocess.Popen, label: str, timeout_s: int = 90) -> None:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited early with code {process.returncode}")
        if _http_ready(url):
            return
        time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready at {url}")


def _frontend_command() -> list[str]:
    yarn = _command_exists("yarn.cmd") or _command_exists("yarn")
    npm = _command_exists("npm.cmd") or _command_exists("npm")
    if yarn:
        return [yarn, "start"]
    if npm:
        return [npm, "start"]
    raise RuntimeError("Node package runner not found. Install Node.js (npm) or Yarn.")


def _require_project_setup() -> None:
    if not (BACKEND / "server.py").exists():
        raise RuntimeError(f"Backend entrypoint not found: {BACKEND / 'server.py'}")
    if not (FRONTEND / "package.json").exists():
        raise RuntimeError(f"Frontend package.json not found: {FRONTEND / 'package.json'}")
    if not (FRONTEND / "node_modules").exists():
        raise RuntimeError(
            "Frontend dependencies are not installed. Run `yarn install` or `npm install` "
            "once inside Trading-Project/frontend, then use this launcher."
        )


def _spawn(command: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    kwargs = {
        "cwd": str(cwd),
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    return subprocess.Popen(command, **kwargs)


def _terminate(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=8)
    except Exception:
        process.kill()


def main() -> int:
    _require_project_setup()
    print("=" * 72)
    print(" Candlestick Representation Learning — Local Control Center")
    print("=" * 72)

    backend_process = None
    frontend_process = None

    try:
        print("[1/3] Starting FastAPI market/data engine...")
        backend_process = _spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            BACKEND,
        )
        _wait_until_ready(BACKEND_HEALTH, backend_process, "Backend")
        print("      Backend ready: http://127.0.0.1:8000")

        print("[2/3] Starting existing React chart workspace...")
        frontend_process = _spawn(
            _frontend_command(),
            FRONTEND,
            {
                # CRA normally opens a browser by itself. This launcher owns that action
                # so only the unified research dashboard is opened.
                "BROWSER": "none",
                "HOST": "127.0.0.1",
            },
        )
        _wait_until_ready("http://127.0.0.1:3000", frontend_process, "Frontend")
        print("      Frontend ready: http://127.0.0.1:3000")

        print("[3/3] Opening unified dashboard...")
        webbrowser.open(FRONTEND_URL, new=2)
        print(f"      {FRONTEND_URL}")
        print()
        print("Everything is running. Close this window or press Ctrl+C to stop it.")

        while True:
            if backend_process.poll() is not None:
                raise RuntimeError(f"Backend stopped with code {backend_process.returncode}")
            if frontend_process.poll() is not None:
                raise RuntimeError(f"Frontend stopped with code {frontend_process.returncode}")
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\nStopping dashboard services...")
        return 0
    except Exception as exc:
        print(f"\nLauncher error: {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate(frontend_process)
        _terminate(backend_process)


if __name__ == "__main__":
    raise SystemExit(main())
