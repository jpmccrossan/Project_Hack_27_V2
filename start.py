"""
start.py — Single entry point for The Assumptionisator.
Run from anywhere: python start.py [--no-refresh] [--interval 900]

  --no-refresh     Disable automatic live price fetching
  --interval N     Seconds between live price refreshes (default: 900 = 15 min)
"""
import os
import sys
import argparse
import subprocess
import threading
import time
from pathlib import Path

APP_DIR     = Path(__file__).parent.resolve()
APP_FILE    = APP_DIR / "app.py"
VENV_PYTHON = APP_DIR / "venv" / "bin" / "python"
REQ_FILE    = APP_DIR / "requirements.txt"
FETCH_LIVE  = APP_DIR / "API_Connection_Files" / "fetch_live.py"


def _python() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _ensure_deps() -> None:
    py = _python()
    print("Checking dependencies…")
    subprocess.run([py, "-m", "pip", "install", "-q", "-r", str(REQ_FILE)],
                   capture_output=True)


def _backup() -> None:
    try:
        from backup import export, prune
        print("Backing up database…")
        export(silent=True)
        prune(keep=10)
        print("Backup complete.")
    except Exception as e:
        print(f"Backup skipped: {e}")


def _live_refresh_loop(interval: int) -> None:
    """Background thread: fetch live prices every `interval` seconds."""
    py = _python()
    while True:
        time.sleep(interval)
        try:
            subprocess.run([py, str(FETCH_LIVE)], capture_output=True, timeout=60)
            print(f"[auto-refresh] Live prices updated at {time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[auto-refresh] Failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch The Assumptionisator")
    parser.add_argument("--no-refresh", action="store_true",
                        help="Disable automatic live price fetching")
    parser.add_argument("--interval", type=int, default=900,
                        help="Seconds between live price refreshes (default: 900)")
    args = parser.parse_args()

    py = _python()
    print(f"\nPython : {py}")
    print(f"App    : {APP_FILE}")
    print()

    _ensure_deps()
    _backup()

    if not args.no_refresh:
        t = threading.Thread(target=_live_refresh_loop, args=(args.interval,), daemon=True)
        t.start()
        print(f"Live price refresh every {args.interval}s in background.")
        print("  Stop with Ctrl+C  |  Disable with --no-refresh\n")
    else:
        print("Live auto-refresh disabled.\n")

    print("Starting The Assumptionisator…")
    print("Open  →  http://localhost:8501\n")

    os.chdir(APP_DIR)
    subprocess.run([py, "-m", "streamlit", "run", str(APP_FILE)])


if __name__ == "__main__":
    main()
