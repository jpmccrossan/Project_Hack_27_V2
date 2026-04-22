"""
Loads fetched data from JSON files into the SQLite database.
Call load_all() after run_all.py has fetched fresh data.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH   = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"
JSON_DIR  = Path(__file__).parent.parent / "Data" / "JSON"


def _get_commodity_id(cur, name: str):
    row = cur.execute("SELECT id FROM commodities WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _get_country_id(cur, name: str):
    row = cur.execute("SELECT id FROM countries WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _get_indicator_id(cur, name: str):
    row = cur.execute("SELECT id FROM macro_indicators WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


# ── Load current snapshots ────────────────────────────────────────────────────

def load_metal_snapshots(cur, data: dict) -> int:
    count = 0
    ts = datetime.now().isoformat()
    for metal, d in data.items():
        comm_id = _get_commodity_id(cur, metal)
        if comm_id and d.get("price") is not None:
            cur.execute(
                "INSERT INTO price_snapshots (commodity_id, price, fetched_at) VALUES (?,?,?)",
                (comm_id, d["price"], ts),
            )
            count += 1
    return count


def load_energy_snapshots(cur, data: dict) -> int:
    count = 0
    ts = datetime.now().isoformat()
    seen = set()
    for region_data in data.values():
        for name, d in region_data.items():
            ticker = d.get("ticker")
            if ticker in seen:
                continue
            seen.add(ticker)
            comm_id = _get_commodity_id(cur, name)
            if comm_id and d.get("price") is not None:
                cur.execute(
                    "INSERT INTO price_snapshots (commodity_id, price, fetched_at) VALUES (?,?,?)",
                    (comm_id, d["price"], ts),
                )
                count += 1
    return count


def load_fx_snapshots(cur, data: dict) -> int:
    count = 0
    ts = datetime.now().isoformat()
    for pair, d in data.get("fx_rates", {}).items():
        comm_id = _get_commodity_id(cur, pair)
        if comm_id and d.get("rate") is not None:
            cur.execute(
                "INSERT INTO price_snapshots (commodity_id, price, fetched_at) VALUES (?,?,?)",
                (comm_id, d["rate"], ts),
            )
            count += 1
    return count


# ── Load historical price data ────────────────────────────────────────────────

def _load_weekly_history(cur, commodity_name: str, entry: dict) -> int:
    count = 0
    comm_id = _get_commodity_id(cur, commodity_name)
    if not comm_id or "data" not in entry:
        return 0
    for year, months in entry["data"].items():
        for month, weeks in months.items():
            for week, d in weeks.items():
                cur.execute(
                    """INSERT OR IGNORE INTO price_history
                       (commodity_id, date, year, month, week, open, high, low, close)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (comm_id, d["date"], int(year), month, week,
                     d.get("open"), d.get("high"), d.get("low"), d.get("close")),
                )
                count += cur.rowcount
    return count


def load_metal_history(cur, data: dict) -> int:
    return sum(_load_weekly_history(cur, name, entry) for name, entry in data.items())


def load_energy_history(cur, data: dict) -> int:
    count = 0
    seen = set()
    for region_data in data.values():
        for name, entry in region_data.items():
            if name in seen:
                continue
            seen.add(name)
            count += _load_weekly_history(cur, name, entry)
    return count


def load_fx_history(cur, data: dict) -> int:
    return sum(_load_weekly_history(cur, pair, entry) for pair, entry in data.get("fx_rates", {}).items())


# ── Load macro data ───────────────────────────────────────────────────────────

def load_macro_data(cur, data: dict) -> int:
    count = 0
    ts = datetime.now().isoformat()
    for country, indicators in data.get("country_indicators", {}).items():
        country_id = _get_country_id(cur, country)
        if not country_id:
            continue
        for ind_name, entry in indicators.items():
            ind_id = _get_indicator_id(cur, ind_name)
            if not ind_id or "data" not in entry:
                continue
            for year, d in entry["data"].items():
                if d.get("value") is None:
                    continue
                cur.execute(
                    """INSERT OR IGNORE INTO macro_data
                       (country_id, indicator_id, year, value, fetched_at)
                       VALUES (?,?,?,?,?)""",
                    (country_id, ind_id, int(year), d["value"], ts),
                )
                count += cur.rowcount
    return count


# ── Master loader ─────────────────────────────────────────────────────────────

def load_all():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Loading data into DB  —  {ts}\n")

    def read(fname):
        p = JSON_DIR / fname
        if not p.exists():
            print(f"  WARNING: {fname} not found — run run_all.py first")
            return {}
        return json.loads(p.read_text())

    metals_snap  = read("metal_prices.json")
    energy_snap  = read("energy_prices.json")
    finance_snap = read("finance_data.json")
    metals_hist  = read("metal_prices_historical.json")
    energy_hist  = read("energy_prices_historical.json")
    finance_hist = read("finance_data_historical.json")

    n = load_metal_snapshots(cur, metals_snap);   print(f"  Metal snapshots:       {n} rows")
    n = load_energy_snapshots(cur, energy_snap);  print(f"  Energy snapshots:      {n} rows")
    n = load_fx_snapshots(cur, finance_snap);     print(f"  FX snapshots:          {n} rows")
    n = load_metal_history(cur, metals_hist);     print(f"  Metal history:         {n} rows")
    n = load_energy_history(cur, energy_hist);    print(f"  Energy history:        {n} rows")
    n = load_fx_history(cur, finance_hist);       print(f"  FX history:            {n} rows")
    n = load_macro_data(cur, finance_hist);       print(f"  Macro (annual):        {n} rows")

    con.commit()
    con.close()
    print(f"\nDone — {DB_PATH}")


if __name__ == "__main__":
    load_all()
