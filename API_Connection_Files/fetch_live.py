"""
fetch_live.py — Fast snapshot-only fetch (metals, energy, FX current prices).
Skips historical data. Runs in ~15s vs ~60s for run_all.py.
Called by start.py on a timer to keep prices live while the app is running.
"""
import sys
import sqlite3
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT))

from metal_data   import get_metal_prices,  save_to_json as metals_json
from energy_data  import get_energy_prices, save_to_json as energy_json
from finance_data import get_fx_rates,      save_to_json as finance_json
from Database.db_loader import load_metal_snapshots, load_energy_snapshots, load_fx_snapshots

DB_PATH = ROOT / "Data" / "jet_engine_costs.db"


def fetch_and_store(verbose: bool = False) -> None:
    if verbose:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching live prices…")

    metals  = get_metal_prices()
    energy  = get_energy_prices()
    fx      = get_fx_rates()

    metals_json(metals)
    energy_json(energy)
    finance_json({"fx_rates": fx, "country_indicators": {}})

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    load_metal_snapshots(cur, metals)
    load_energy_snapshots(cur, energy)
    load_fx_snapshots(cur, {"fx_rates": fx})
    con.commit()
    con.close()

    if verbose:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Live prices updated.")


if __name__ == "__main__":
    fetch_and_store(verbose=True)
