"""
Database layer for the Assumption Tracker.
Stores assumption_tracker and assumption_audit_log tables in the main
jet_engine_costs.db so the LLM can query everything in one place.
"""
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_tracker_tables() -> None:
    """Create assumption_tracker and assumption_audit_log tables if they don't exist."""
    con = _conn()
    c = con.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS assumption_tracker (
            assumption_id TEXT PRIMARY KEY,
            project_name TEXT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            owner TEXT NOT NULL,
            description TEXT,
            baseline_value REAL,
            current_value REAL,
            unit TEXT,
            internal_drift_pct REAL DEFAULT 0,
            external_drift_pct REAL DEFAULT 0,
            confidence_score INTEGER DEFAULT 50,
            last_review_date TEXT,
            review_interval_days INTEGER DEFAULT 30,
            dependencies TEXT,
            status TEXT DEFAULT 'Open',
            created_at TEXT,
            updated_at TEXT,
            ai_classification TEXT,
            ai_risk_level TEXT,
            ai_rationale TEXT,
            ai_assessed_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS assumption_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            assumption_id TEXT NOT NULL,
            action TEXT NOT NULL,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            user TEXT DEFAULT 'system',
            change_reason TEXT
        )
    """)
    con.commit()
    con.close()


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return str(value)
    return str(value)


def _log(assumption_id: str, action: str, field_name: Optional[str] = None,
         old_value: Any = None, new_value: Any = None,
         user: str = "system", change_reason: str = "") -> None:
    con = _conn()
    con.execute(
        "INSERT INTO assumption_audit_log "
        "(timestamp, assumption_id, action, field_name, old_value, new_value, user, change_reason) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), assumption_id, action, field_name,
         _serialize(old_value), _serialize(new_value), user, change_reason),
    )
    con.commit()
    con.close()


def load_tracker() -> List[Dict[str, Any]]:
    con = _conn()
    rows = con.execute("SELECT * FROM assumption_tracker ORDER BY assumption_id").fetchall()
    con.close()
    result = []
    for row in rows:
        r = dict(row)
        if r.get("last_review_date"):
            try:
                r["last_review_date"] = datetime.strptime(r["last_review_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                r["last_review_date"] = date.today()
        result.append(r)
    return result


def add_tracker_row(row: Dict[str, Any], user: str = "system", change_reason: str = "") -> None:
    con = _conn()
    now = datetime.now().isoformat()
    last_review = row.get("last_review_date")
    if isinstance(last_review, date) and not isinstance(last_review, datetime):
        last_review = last_review.isoformat()
    elif last_review is None:
        last_review = date.today().isoformat()

    con.execute(
        "INSERT INTO assumption_tracker "
        "(assumption_id, project_name, title, category, owner, description, baseline_value, current_value, "
        "unit, internal_drift_pct, external_drift_pct, confidence_score, last_review_date, "
        "review_interval_days, dependencies, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["assumption_id"], row.get("project_name", ""),
         row["title"], row["category"], row["owner"],
         row.get("description", ""), row.get("baseline_value", 0), row.get("current_value", 0),
         row.get("unit", ""), row.get("internal_drift_pct", 0), row.get("external_drift_pct", 0),
         row.get("confidence_score", 50), last_review, row.get("review_interval_days", 30),
         row.get("dependencies", ""), row.get("status", "Open"), now, now),
    )
    con.commit()
    con.close()
    _log(row["assumption_id"], "CREATE", user=user,
         change_reason=change_reason or "Initial creation")


def update_tracker_row(assumption_id: str, updates: Dict[str, Any],
                       user: str = "system", change_reason: str = "") -> None:
    con = _conn()
    now = datetime.now().isoformat()
    cur = dict(con.execute(
        "SELECT * FROM assumption_tracker WHERE assumption_id=?", (assumption_id,)
    ).fetchone() or {})

    clauses, values = [], []
    for key, new_val in updates.items():
        if key in cur:
            old_val = cur[key]
            if key == "last_review_date":
                if isinstance(new_val, date) and not isinstance(new_val, datetime):
                    new_val = new_val.isoformat()
                if new_val is None:
                    new_val = date.today().isoformat()
            if old_val != new_val:
                _log(assumption_id, "UPDATE", field_name=key,
                     old_value=old_val, new_value=new_val,
                     user=user, change_reason=change_reason)
            clauses.append(f"{key} = ?")
            values.append(new_val)

    if clauses:
        clauses.append("updated_at = ?")
        values += [now, assumption_id]
        con.execute(
            f"UPDATE assumption_tracker SET {', '.join(clauses)} WHERE assumption_id=?",
            values,
        )
        con.commit()
    con.close()


def delete_tracker_row(assumption_id: str) -> None:
    con = _conn()
    con.execute("DELETE FROM assumption_audit_log WHERE assumption_id=?", (assumption_id,))
    con.execute("DELETE FROM assumption_tracker WHERE assumption_id=?", (assumption_id,))
    con.commit()
    con.close()


def delete_all_tracker_rows() -> None:
    con = _conn()
    con.execute("DELETE FROM assumption_audit_log")
    con.execute("DELETE FROM assumption_tracker")
    con.commit()
    con.close()


def get_audit_log(assumption_id: Optional[str] = None) -> List[Dict[str, Any]]:
    con = _conn()
    if assumption_id:
        rows = con.execute(
            "SELECT * FROM assumption_audit_log WHERE assumption_id=? ORDER BY timestamp DESC",
            (assumption_id,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM assumption_audit_log ORDER BY timestamp DESC"
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def seed_if_empty(seed_records: List[Dict[str, Any]]) -> None:
    con = _conn()
    count = con.execute("SELECT COUNT(*) FROM assumption_tracker").fetchone()[0]
    con.close()
    if count == 0:
        for r in seed_records:
            add_tracker_row(r, user="system", change_reason="Initial seed")
