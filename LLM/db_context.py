"""
db_context.py — Database schema + SQL execution for LLM Data Chat.
The LLM is given the schema and writes its own SQL queries.
We execute them and feed results back so it can reason from real data.
"""
import re
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"

_SAFE_SQL = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


def _con():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _q(sql, params=()):
    con = _con()
    try:
        df = pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()
    return df


def jic_label(pct):
    if pct is None or (isinstance(pct, float) and pd.isna(pct)):
        return "Unknown"
    thresholds = [
        (5.0, "Remote Chance"), (22.5, "Highly Unlikely"), (37.5, "Unlikely"),
        (52.5, "Realistic Possibility"), (77.5, "Likely or Probable"),
        (92.5, "Highly Likely"),
    ]
    for threshold, label in thresholds:
        if float(pct) <= threshold:
            return label
    return "Almost Certain"


def get_gbp_usd():
    try:
        df = _q(
            "SELECT ps.price FROM price_snapshots ps"
            " JOIN commodities c ON ps.commodity_id = c.id"
            " WHERE c.name IN ('GBP/USD','GBPUSD=X') ORDER BY ps.id DESC LIMIT 1"
        )
        if not df.empty:
            rate = float(df["price"].iloc[0])
            return rate if rate > 0 else 1.27
    except Exception:
        pass
    return 1.27


def get_all_table_names():
    df = _q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return df["name"].tolist() if not df.empty else []


def get_row_count(table):
    try:
        df = _q("SELECT COUNT(*) AS n FROM [{}]".format(table))
        return int(df["n"].iloc[0])
    except Exception:
        return -1


def execute_sql(query: str) -> str:
    """
    Safely execute a SELECT query and return results as a formatted string.
    Rejects non-SELECT statements. Returns error text on failure.
    """
    query = query.strip()
    if not _SAFE_SQL.match(query):
        return "ERROR: Only SELECT queries are permitted."
    try:
        df = _q(query)
        if df.empty:
            return "Query returned 0 rows."
        result = df.head(200).to_string(index=False)
        if len(df) > 200:
            result += "\n[Showing 200 of {:,} rows]".format(len(df))
        return result
    except Exception as e:
        return "SQL ERROR: {}".format(str(e))


def _build_schema_description():
    """Compact schema — enough for the model to write correct SQL, nothing more."""
    lines = []

    # Commodity names grouped by category (needed for WHERE c.name = '...' clauses)
    comms = _q("""
        SELECT c.name, c.ticker, c.unit, cat.name AS cat
        FROM commodities c JOIN categories cat ON c.category_id = cat.id
        ORDER BY cat.name, c.name
    """)
    if not comms.empty:
        lines.append("commodities (id, name, category_id, unit, ticker):")
        for cat, grp in comms.groupby("cat"):
            entries = ", ".join(
                '"{}" [{}]'.format(r["name"], r["unit"]) for _, r in grp.iterrows()
            )
            lines.append("  [{}] {}".format(cat, entries))

    lines.append("""
price_snapshots (commodity_id, price [USD], fetched_at)
  Latest price: WHERE id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)

price_history (commodity_id, date [YYYY-MM-DD], close [USD])
  Weekly data 2021-present. 1-year change: compare snapshot vs WHERE date <= DATE('now','-1 year')

assumptions (assumption_id, project_id, project_name, assumption_type [boolean|economic|material|energy],
  assumption, ticker, price_per_unit, currency, unit, qty, total_cost,
  ai_classification, ai_risk_level, ai_rationale)
  8 projects: Engine Casing, Fan blade manufacturing, Compressor assembly, Chamber fabrication,
  Turbine manufacturing, Nozzle assembly, Bearing assembly, Fuel system components.
  JOIN commodities ON c.ticker = a.ticker||'=F' OR c.ticker = a.ticker

projects (project_id, project_name, customer_name, budget_gbp, budget_threshold_pct,
  confidence_score, status [Active|Monitor|At Risk|On Hold|Complete])

project_audit_log (project_id, timestamp, field_name, old_value, new_value, user, change_reason)
  Confidence history: WHERE field_name='confidence_score' ORDER BY timestamp

assumption_tracker (assumption_id [ASXXX], project_name, title, category, owner, description,
  baseline_value, current_value, unit, internal_drift_pct, external_drift_pct,
  confidence_score, last_review_date [YYYY-MM-DD], review_interval_days [INTEGER days],
  dependencies, status [Open|Monitor|Mitigated|Closed],
  ai_classification, ai_risk_level, ai_rationale)
  Overdue check: CAST((julianday('now') - julianday(last_review_date)) AS INTEGER) > review_interval_days
  Days overdue: CAST((julianday('now') - julianday(last_review_date)) AS INTEGER) - review_interval_days
  Example: SELECT assumption_id, title, owner, last_review_date, review_interval_days,
    CAST((julianday('now') - julianday(last_review_date)) AS INTEGER) AS days_since_review,
    CAST((julianday('now') - julianday(last_review_date)) AS INTEGER) - review_interval_days AS days_overdue
    FROM assumption_tracker
    WHERE CAST((julianday('now') - julianday(last_review_date)) AS INTEGER) > review_interval_days
    ORDER BY days_overdue DESC

assumption_audit_log (timestamp, assumption_id, field_name, old_value, new_value, user)

macro_data (country_id, indicator_id, value, year)
countries (id, name) -- UK=1, US=2, Australia=3, Canada=4, Japan=5, Germany=6, France=7, China=8
macro_indicators (id, name) -- CPI=1, GDP Growth=2, Unemployment=3, Lending Rate=4, Real Interest=5
component_materials (component_id, commodity_id, notes)
jet_engine_components (id, name) -- query: SELECT id,name FROM jet_engine_components""")

    return "\n".join(lines)


def build_full_system_prompt():
    """
    Build the LLM system prompt: schema + SQL tool instructions.
    No hardcoded data — the model queries what it needs.
    """
    from datetime import datetime as _dt
    gbp_usd    = get_gbp_usd()
    schema     = _build_schema_description()
    today      = _dt.now().strftime("%Y-%m-%d")
    time_now   = _dt.now().strftime("%Y-%m-%d %H:%M")

    # Fetch the actual last data fetch timestamp from DB
    try:
        last_fetch_df = _q("SELECT MAX(fetched_at) AS ts FROM price_snapshots")
        last_fetch = last_fetch_df["ts"].iloc[0] if not last_fetch_df.empty else "unknown"
    except Exception:
        last_fetch = "unknown"

    return (
        "You are a cost intelligence analyst at Rolls-Royce with live access to a SQLite database.\n\n"

        "## DATE & DATA FRESHNESS\n"
        "Today's date: {today}. Current time: {now}.\n"
        "Market data last fetched: {fetch}.\n"
        "IMPORTANT: Use these actual dates — never use training-data dates.\n"
        "To find the latest price date: SELECT MAX(fetched_at) FROM price_snapshots\n\n".format(
            today=today, now=time_now, fetch=last_fetch
        ) +

        "## HOW TO QUERY DATA\n"
        "Write SQL between ```sql and ``` tags. The system executes it and returns results to you.\n"
        "Use multiple queries if needed. If a query errors, read the error and fix it.\n"
        "ALWAYS query for specific numbers — never guess or make up values.\n"
        "Only SELECT is permitted.\n\n"

        "## SQLITE DATE FUNCTIONS (this is SQLite — not SQL Server, MySQL, or PostgreSQL)\n"
        "NEVER use: DATEDIFF, DATEADD, GETDATE, NOW(), CURRENT_TIMESTAMP as a function call.\n"
        "ALWAYS use these SQLite equivalents:\n"
        "  Days between two dates:  CAST((julianday(date2) - julianday(date1)) AS INTEGER)\n"
        "  Days since a date:       CAST((julianday('now') - julianday(some_date)) AS INTEGER)\n"
        "  Today's date:            DATE('now')\n"
        "  N days ago:              DATE('now', '-N days')  e.g. DATE('now', '-30 days')\n"
        "  N days in future:        DATE('now', '+N days')\n"
        "  Overdue check:           julianday('now') - julianday(last_review_date) > review_interval_days\n\n"

        "## CONVERSION\n"
        "GBP/USD rate: {:.4f}. GBP = USD ÷ {:.4f}. Always show both currencies.\n\n".format(gbp_usd, gbp_usd) +

        "## JIC RISK SCALE (based on 1-year % price change)\n"
        "≤5% Remote | ≤22.5% Highly Unlikely | ≤37.5% Unlikely | "
        "≤52.5% Realistic Possibility | ≤77.5% Likely | ≤92.5% Highly Likely | >92.5% Almost Certain\n\n"

        "## DATABASE SCHEMA\n"
        "{}\n\n".format(schema) +

        "## RULES\n"
        "- Answer immediately after receiving query results. No filler phrases.\n"
        "- Always state the data date (from fetched_at or price_history.date) when reporting prices.\n"
        "- Every price: show USD and GBP, 1Y % change, JIC level.\n"
        "- Every risk assessment: end with one concrete action (hedge/lock/monitor/substitute).\n"
        "- If data is not in the DB, say so explicitly.\n"
    )
