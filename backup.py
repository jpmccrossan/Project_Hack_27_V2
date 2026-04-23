"""
backup.py — Export all database tables to timestamped CSV files.
Run manually: python backup.py
Also called automatically by start.py on each launch.
"""
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path

DB_PATH    = Path(__file__).parent / "Data" / "jet_engine_costs.db"
BACKUP_DIR = Path(__file__).parent / "Data" / "backups"

# Tables to skip (very large / easily re-fetched from APIs)
_SKIP = {"price_history"}


def export(silent: bool = False) -> Path:
    """Export all tables to Data/backups/<timestamp>/ and return the folder."""
    if not DB_PATH.exists():
        if not silent:
            print(f"Database not found: {DB_PATH}")
        return BACKUP_DIR

    ts  = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = BACKUP_DIR / ts
    out.mkdir(parents=True, exist_ok=True)

    con    = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]

    for table in tables:
        if table in _SKIP:
            continue
        df = pd.read_sql_query(f"SELECT * FROM [{table}]", con)
        path = out / f"{table}.csv"
        df.to_csv(path, index=False)
        if not silent:
            print(f"  {table:<35} {len(df):>5} rows  →  {path.name}")

    con.close()
    if not silent:
        print(f"\nBackup saved to {out}")
    return out


def prune(keep: int = 10) -> None:
    """Keep only the most recent N backups, delete older ones."""
    if not BACKUP_DIR.exists():
        return
    folders = sorted(BACKUP_DIR.iterdir(), reverse=True)
    for old in folders[keep:]:
        if old.is_dir():
            for f in old.iterdir():
                f.unlink()
            old.rmdir()


if __name__ == "__main__":
    export()
    prune(keep=10)
