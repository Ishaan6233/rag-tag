from __future__ import annotations

import os
import time
import signal
import subprocess
import sys
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"


def _run(cmd: list[str], cwd: Path) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=os.environ.copy(),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def main() -> int:
    if not (WEB_DIR / "package.json").is_file():
        print("web/package.json not found. Run from repo root.", file=sys.stderr)
        return 1

    uvicorn_cmd = [
        "uv",
        "run",
        "uvicorn",
        "server.app:app",
        "--reload",
        "--port",
        "8000",
    ]
    npm_path = shutil.which("npm")
    if npm_path is None:
        print(
            "npm not found in PATH. Install Node.js or run the frontend manually:",
            file=sys.stderr,
        )
        print("  cd web", file=sys.stderr)
        print("  npm install", file=sys.stderr)
        print("  npm run dev", file=sys.stderr)
        return 1

    vite_cmd = [npm_path, "run", "dev"]

    print("Starting backend (uvicorn) and frontend (vite)...")
    backend = _run(uvicorn_cmd, REPO_ROOT)
    frontend = _run(vite_cmd, WEB_DIR)

    try:
        while True:
            backend.poll()
            frontend.poll()
            if backend.returncode is not None:
                print("Backend exited; shutting down frontend.")
                break
            if frontend.returncode is not None:
                print("Frontend exited; shutting down backend.")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        for proc in (backend, frontend):
            if proc.poll() is None:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
