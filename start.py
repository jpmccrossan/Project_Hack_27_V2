"""
start.py — Full bootstrap launcher for The Assumptionisator.
Run with any Python from any directory: python start.py

What it does (in order):
  1. Creates a virtual environment if one doesn't exist
  2. Re-launches itself inside the venv (so all installs go to the right place)
  3. Installs / upgrades requirements from requirements.txt
  4. Builds the database schema (safe to re-run — uses IF NOT EXISTS)
  5. Fetches initial market data if price_snapshots is empty
  6. Backs up the database
  7. Starts a background thread that refreshes live prices every 15 min
  8. Launches the Streamlit app at http://localhost:8501

Does NOT install Ollama or pull LLM models — do those manually:
  brew install ollama   (or https://ollama.com)
  ollama pull llama3.2
"""
import os
import sys
import subprocess
import threading
import time
from pathlib import Path

# ── Paths — all absolute, derived from this file's location ───────────────────
# APP_DIR is always the project root regardless of where you run the script from.
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
    if VENV_PY_W.exists():
        return VENV_PY_W
    if VENV_PY.exists():
        return VENV_PY
    py3 = VENV_DIR / "bin" / "python3"
    if py3.exists():
        return py3
    return VENV_PY  # fallback — will trigger creation on next run


def _in_venv() -> bool:
    return Path(sys.executable).resolve() == _venv_python().resolve()


def _banner(msg: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {msg}")
    print(f"{'─' * 50}")


def _run(*args, **kwargs):
    """subprocess.run with cwd always set to APP_DIR."""
    kwargs.setdefault("cwd", str(APP_DIR))
    return subprocess.run(*args, **kwargs)


# ── Step 1: create venv if missing ────────────────────────────────────────────
def _ensure_venv() -> None:
    if VENV_DIR.exists():
        return
    _banner("Creating virtual environment…")
    _run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print("  venv created.")


# ── Step 2: re-launch inside venv ─────────────────────────────────────────────
def _relaunch_in_venv() -> None:
    """If not running inside the project venv, restart with it."""
    vpy = _venv_python()
    if not vpy.exists():
        return  # venv not ready yet
    if _in_venv():
        return  # already inside venv
    print(f"  Switching to venv Python: {vpy}")
    if sys.platform == "win32":
        # os.execv on Windows doesn't replace the process — use subprocess + exit.
        result = _run([str(vpy)] + sys.argv)
        sys.exit(result.returncode)
    else:
        # On Unix, execv replaces the current process cleanly.
        os.chdir(APP_DIR)
        os.execv(str(vpy), [str(vpy)] + sys.argv)


# ── Step 3: install requirements ──────────────────────────────────────────────
def _install_deps() -> None:
    _banner("Installing / checking dependencies…")
    _run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        check=False,
    )
    result = _run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(REQ_FILE)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("  All dependencies satisfied.")
    else:
        print("  WARNING: some packages may not have installed correctly.")
        print(result.stderr[:400])


# ── Step 4: build DB schema + fetch data if needed ────────────────────────────
def _ensure_data() -> None:
    # Build DB schema first — safe to call every time (uses IF NOT EXISTS).
    # This creates the Data/ folder, all tables, and seeds reference data.
    _banner("Initialising database schema…")
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    try:
        from Database.db_setup import build as _db_build
        _db_build()
        print("  Schema ready.")
    except Exception as e:
        print(f"  WARNING: DB schema setup failed: {e}")

    # Check whether market price data is already present
    needs_fetch = False
    import sqlite3
    try:
        con = sqlite3.connect(str(DB_FILE))
        n = con.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        con.close()
        if n == 0:
            needs_fetch = True
            print("  No price data found — fetching market data…")
        else:
            print(f"  Price data present ({n} snapshots).")
    except Exception:
        needs_fetch = True
        print("  Could not read price data — fetching market data…")

    if needs_fetch:
        _banner("Fetching market data (first time — takes ~60s)…")
        _run([sys.executable, str(RUN_ALL)], check=False)
        print("  Initial data fetch complete.")
    else:
        print(f"  Database: {DB_FILE.name}")


# ── Step 5: backup ────────────────────────────────────────────────────────────
def _backup() -> None:
    try:
        if str(APP_DIR) not in sys.path:
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
                _run(
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
    _run([sys.executable, "-m", "streamlit", "run", str(APP_FILE)])


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("\n✈  The Assumptionisator — Project Hack 27")
    print(f"  Script : {Path(__file__).resolve()}")

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
