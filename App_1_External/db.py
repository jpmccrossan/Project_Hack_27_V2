"""Database layer for assumptions tracker with audit history."""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "tracker.db"


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database tables if they don't exist."""
    conn = _get_connection()
    c = conn.cursor()

    # Assumptions table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS assumptions (
            assumption_id TEXT PRIMARY KEY,
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
            updated_at TEXT
        )
        """
    )

    # Audit log table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            assumption_id TEXT NOT NULL,
            action TEXT NOT NULL,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            user TEXT DEFAULT 'system',
            change_reason TEXT,
            FOREIGN KEY (assumption_id) REFERENCES assumptions(assumption_id)
        )
        """
    )

    conn.commit()
    conn.close()


def _serialize_value(value: Any) -> str:
    """Convert value to storable string."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return str(value)
    return str(value)


def _log_change(
    assumption_id: str,
    action: str,
    field_name: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    user: str = "system",
    change_reason: str = "",
) -> None:
    """Log a change to the audit log."""
    conn = _get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        """
        INSERT INTO audit_log
        (timestamp, assumption_id, action, field_name, old_value, new_value, user, change_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            assumption_id,
            action,
            field_name,
            _serialize_value(old_value),
            _serialize_value(new_value),
            user,
            change_reason,
        ),
    )
    conn.commit()
    conn.close()


def load_assumptions() -> List[Dict[str, Any]]:
    """Load all assumptions from database."""
    conn = _get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM assumptions ORDER BY assumption_id")
    rows = c.fetchall()
    conn.close()

    result = []
    for row in rows:
        record = dict(row)
        # Convert date strings back to date objects where needed
        if record["last_review_date"]:
            try:
                record["last_review_date"] = datetime.strptime(
                    record["last_review_date"], "%Y-%m-%d"
                ).date()
            except (ValueError, TypeError):
                record["last_review_date"] = date.today()
        result.append(record)

    return result


def add_assumption(assumption: Dict[str, Any], user: str = "system", change_reason: str = "") -> None:
    """Add a new assumption to the database."""
    conn = _get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()

    assumption_id = assumption["assumption_id"]

    # Normalize date fields
    last_review = assumption.get("last_review_date")
    if isinstance(last_review, date) and not isinstance(last_review, datetime):
        last_review = last_review.isoformat()
    elif last_review is None:
        last_review = date.today().isoformat()

    c.execute(
        """
        INSERT INTO assumptions
        (assumption_id, title, category, owner, description, baseline_value, current_value,
         unit, internal_drift_pct, external_drift_pct, confidence_score, last_review_date,
         review_interval_days, dependencies, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assumption["assumption_id"],
            assumption["title"],
            assumption["category"],
            assumption["owner"],
            assumption.get("description", ""),
            assumption.get("baseline_value", 0),
            assumption.get("current_value", 0),
            assumption.get("unit", ""),
            assumption.get("internal_drift_pct", 0),
            assumption.get("external_drift_pct", 0),
            assumption.get("confidence_score", 50),
            last_review,
            assumption.get("review_interval_days", 30),
            assumption.get("dependencies", ""),
            assumption.get("status", "Open"),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    _log_change(
        assumption_id,
        "CREATE",
        user=user,
        change_reason=change_reason or "Initial assumption creation",
    )


def update_assumption(assumption_id: str, updates: Dict[str, Any], user: str = "system", change_reason: str = "") -> None:
    """Update an assumption and log the changes."""
    conn = _get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()

    # Fetch current values
    c.execute("SELECT * FROM assumptions WHERE assumption_id = ?", (assumption_id,))
    current = dict(c.fetchone() or {})

    # Prepare update statement
    set_clauses = []
    values = []
    for key, new_val in updates.items():
        if key in current:
            old_val = current[key]
            # Normalize dates
            if key == "last_review_date":
                if isinstance(new_val, date) and not isinstance(new_val, datetime):
                    new_val = new_val.isoformat()
                if new_val is None:
                    new_val = date.today().isoformat()

            # Log the change
            if old_val != new_val:
                _log_change(
                    assumption_id,
                    "UPDATE",
                    field_name=key,
                    old_value=old_val,
                    new_value=new_val,
                    user=user,
                    change_reason=change_reason,
                )

            set_clauses.append(f"{key} = ?")
            values.append(new_val)

    if set_clauses:
        set_clauses.append("updated_at = ?")
        values.append(now)
        values.append(assumption_id)

        query = f"UPDATE assumptions SET {', '.join(set_clauses)} WHERE assumption_id = ?"
        c.execute(query, values)
        conn.commit()

    conn.close()


def delete_assumption(assumption_id: str, user: str = "system") -> None:
    """Soft delete an assumption (mark as closed and log)."""
    conn = _get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute(
        "UPDATE assumptions SET status = ?, updated_at = ? WHERE assumption_id = ?",
        ("Closed", now, assumption_id),
    )
    conn.commit()
    conn.close()

    _log_change(
        assumption_id,
        "DELETE",
        user=user,
        change_reason="Assumption deleted",
    )


def delete_assumption_permanent(assumption_id: str) -> None:
    """Permanently delete a single assumption and its audit entries."""
    conn = _get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM audit_log WHERE assumption_id = ?", (assumption_id,))
    c.execute("DELETE FROM assumptions WHERE assumption_id = ?", (assumption_id,))
    conn.commit()
    conn.close()


def get_audit_history(assumption_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch audit history, optionally filtered by assumption_id."""
    conn = _get_connection()
    c = conn.cursor()

    if assumption_id:
        c.execute(
            """
            SELECT * FROM audit_log
            WHERE assumption_id = ?
            ORDER BY timestamp DESC
            """,
            (assumption_id,),
        )
    else:
        c.execute(
            """
            SELECT * FROM audit_log
            ORDER BY timestamp DESC
            """
        )

    rows = c.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def seed_db_if_empty(seed_records: List[Dict[str, Any]]) -> None:
    """Seed database with initial records if empty."""
    conn = _get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM assumptions")
    count = c.fetchone()[0]
    conn.close()

    if count == 0:
        for record in seed_records:
            add_assumption(record, user="system")


def delete_all_data() -> None:
    """Clear all data (for reset button)."""
    conn = _get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM audit_log")
    c.execute("DELETE FROM assumptions")
    conn.commit()
    conn.close()


def delete_all_assumptions_permanent() -> None:
    """Permanently delete all assumptions and their audit history entries."""
    delete_all_data()


def reset_and_seed_data(seed_records: List[Dict[str, Any]]) -> None:
    """Replace all stored data with the provided seed records."""
    delete_all_data()
    for record in seed_records:
        add_assumption(record, user="system", change_reason="Database reset seed")
