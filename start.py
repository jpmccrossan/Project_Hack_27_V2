"""
start.py — Full bootstrap launcher for The Assumptionisator.
Run with any Python: python start.py

What it does (in order):
  1. Creates a virtual environment if one doesn't exist
  2. Re-launches itself inside the venv (so all installs go to the right place)
  3. Installs / upgrades requirements from requirements.txt
  4. Fetches initial market data if the database is missing or empty
  5. Backs up the database
  6. Starts a background thread that refreshes live prices every 15 min
  7. Launches the Streamlit app at http://localhost:8501

Does NOT install Ollama or pull LLM models — do those manually:
  brew install ollama   (or https://ollama.com)
  ollama pull qwen2.5-coder:7b
"""
import os
import sys
import subprocess
import threading
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
APP_DIR    = Path(__file__).parent.resolve()
VENV_DIR   = APP_DIR / "venv"
VENV_PY    = VENV_DIR / "bin" / "python"          # Linux / Mac
VENV_PY_W  = VENV_DIR / "Scripts" / "python.exe"  # Windows
REQ_FILE   = APP_DIR / "requirements.txt"
APP_FILE   = APP_DIR / "app.py"
DB_FILE    = APP_DIR / "Data" / "jet_engine_costs.db"
RUN_ALL    = APP_DIR / "API_Connection_Files" / "run_all.py"
FETCH_LIVE = APP_DIR / "API_Connection_Files" / "fetch_live.py"


def _venv_python() -> Path:
    return VENV_PY_W if VENV_PY_W.exists() else VENV_PY


def _in_venv() -> bool:
    """True if the current interpreter is the project venv."""
    return Path(sys.executable).resolve() == _venv_python().resolve()


def _banner(msg: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {msg}")
    print(f"{'─' * 50}")


# ── Step 1: create venv if missing ────────────────────────────────────────────
def _ensure_venv() -> None:
    if VENV_DIR.exists():
        return
    _banner("Creating virtual environment…")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print("  venv created.")


# ── Step 2: re-launch inside venv ─────────────────────────────────────────────
def _relaunch_in_venv() -> None:
    """If we're not running inside the project venv, restart with it."""
    vpy = _venv_python()
    if not vpy.exists():
        return  # no venv yet — will be created then we re-run
    if _in_venv():
        return  # already inside venv
    print(f"  Switching to venv Python: {vpy}")
    os.chdir(APP_DIR)
    os.execv(str(vpy), [str(vpy)] + sys.argv)  # replace current process


# ── Step 3: install requirements ──────────────────────────────────────────────
def _install_deps() -> None:
    _banner("Installing / checking dependencies…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        check=False,
    )
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(REQ_FILE)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("  All dependencies satisfied.")
    else:
        print("  WARNING: some packages may not have installed correctly.")
        print(result.stderr[:400])


# ── Step 4: fetch initial data if DB is missing / empty ───────────────────────
def _ensure_data() -> None:
    needs_fetch = False
    if not DB_FILE.exists():
        needs_fetch = True
        print("\n  Database not found — fetching initial market data…")
    else:
        import sqlite3
        try:
            con = sqlite3.connect(DB_FILE)
            n = con.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
            con.close()
            if n == 0:
                needs_fetch = True
                print("\n  Database empty — fetching initial market data…")
        except Exception:
            needs_fetch = True

    if needs_fetch:
        _banner("Fetching market data (first time — takes ~60s)…")
        subprocess.run([sys.executable, str(RUN_ALL)], check=False)
        print("  Initial data fetch complete.")
    else:
        print(f"\n  Database found ({DB_FILE.name}).")


# ── Step 5: backup ────────────────────────────────────────────────────────────
def _backup() -> None:
    try:
        sys.path.insert(0, str(APP_DIR))
        from backup import export, prune
        export(silent=True)
        prune(keep=10)
        print("  Database backed up.")
    except Exception as e:
        print(f"  Backup skipped ({e}).")


# ── Step 6: live price refresh thread ─────────────────────────────────────────
def _start_refresh_thread(interval: int = 900) -> None:
    def _loop():
        while True:
            time.sleep(interval)
            try:
                subprocess.run(
                    [sys.executable, str(FETCH_LIVE)],
                    capture_output=True, timeout=90,
                )
                print(f"[{time.strftime('%H:%M:%S')}] Live prices refreshed.")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Refresh failed: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"  Live price refresh every {interval // 60} min in background.")


# ── Step 7: launch Streamlit ──────────────────────────────────────────────────
def _launch() -> None:
    _banner("Starting The Assumptionisator…")
    print("  Open →  http://localhost:8501")
    print("  Stop  →  Ctrl+C\n")
    os.chdir(APP_DIR)
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(APP_FILE)])


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("\n✈  The Assumptionisator — Project Hack 27")

    _ensure_venv()
    _relaunch_in_venv()   # restarts process inside venv if needed

    # Everything below runs inside the venv
    print(f"  Python  : {sys.executable}")
    print(f"  App dir : {APP_DIR}")

    _install_deps()
    _ensure_data()
    _backup()
    _start_refresh_thread(interval=900)
    _launch()


if __name__ == "__main__":
    main()
