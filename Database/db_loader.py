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


# ── Load assumptions CSV ──────────────────────────────────────────────────────

def load_assumptions_csv(cur) -> tuple:
    """Load HPO_Assumptions_data.csv into both assumptions (external) and
    assumption_tracker (internal) tables. Returns (ext_count, int_count)."""
    import csv
    csv_path = Path(__file__).parent.parent / "Data" / "CSV" / "HPO_Assumptions_data.csv"
    if not csv_path.exists():
        print("  WARNING: HPO_Assumptions_data.csv not found in Data/CSV/")
        return 0, 0

    def to_float(v):
        try:
            return float(v) if v not in (None, "", "nan") else None
        except (ValueError, TypeError):
            return None

    def to_int(v):
        try:
            return int(float(v)) if v not in (None, "", "nan") else None
        except (ValueError, TypeError):
            return None

    ext_count = 0
    int_count = 0
    ts = datetime.now().isoformat()

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            scope = row.get("assumption_scope", "external").strip().lower()

            if scope == "external":
                cur.execute(
                    """INSERT OR REPLACE INTO assumptions
                           (assumption_id, project_id, project_name, category, assumption_type,
                            location, assumption, ticker, event_date, price_per_unit, currency,
                            unit, qty, total_cost, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        to_int(row["assumption_id"]),
                        to_int(row.get("project_id")),
                        row.get("project_name", ""),
                        row.get("category", ""),
                        row.get("assumption_type", ""),
                        row.get("location", ""),
                        row.get("assumption", ""),
                        row.get("ticker", ""),
                        row.get("event_date", ""),
                        to_float(row.get("price_per_unit")),
                        row.get("currency", ""),
                        row.get("unit", ""),
                        to_float(row.get("qty")),
                        to_float(row.get("total_cost")),
                        ts,
                    ),
                )
                ext_count += 1

            elif scope == "internal":
                # INSERT OR IGNORE — preserves live UI updates; only seeds on first run
                cur.execute(
                    """INSERT OR IGNORE INTO assumption_tracker
                           (assumption_id, project_name, title, category, owner, description,
                            baseline_value, current_value, unit, internal_drift_pct, external_drift_pct,
                            confidence_score, last_review_date, review_interval_days,
                            dependencies, status, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["assumption_id"].strip(),
                        row.get("project_name", ""),
                        row.get("title", ""),
                        row.get("category", ""),
                        row.get("owner", ""),
                        row.get("description", ""),
                        to_float(row.get("baseline_value")),
                        to_float(row.get("current_value")),
                        row.get("unit_internal", "") or row.get("unit", ""),
                        to_float(row.get("internal_drift_pct")) or 0.0,
                        to_float(row.get("external_drift_pct")) or 0.0,
                        to_int(row.get("confidence_score")) or 50,
                        row.get("last_review_date", "") or ts[:10],
                        to_int(row.get("review_interval_days")) or 30,
                        row.get("dependencies", ""),
                        row.get("status", "Open"),
                        ts,
                        ts,
                    ),
                )
                int_count += 1

    return ext_count, int_count


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
    ext, int_ = load_assumptions_csv(cur)
    print(f"  Assumptions (ext):     {ext} rows")
    print(f"  Assumptions (int):     {int_} rows")

    con.commit()
    con.close()
    print(f"\nDone — {DB_PATH}")


if __name__ == "__main__":
    load_all()
