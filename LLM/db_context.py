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
    """
    Build a rich schema description with table purposes, column names,
    and sample values for small lookup tables so the model can write correct SQL.
    """
    lines = []

    # ── Lookup tables with sample values ──────────────────────────────────────
    cats = _q("SELECT id, name FROM categories ORDER BY name")
    if not cats.empty:
        vals = ", ".join("{} (id={})".format(r["name"], r["id"]) for _, r in cats.iterrows())
        lines.append("categories: " + vals)

    comms = _q("""
        SELECT c.name, c.unit, cat.name AS category
        FROM commodities c JOIN categories cat ON c.category_id = cat.id
        ORDER BY cat.name, c.name
    """)
    if not comms.empty:
        lines.append("\ncommodities (id, name, category_id, unit, ticker, source):")
        for cat, grp in comms.groupby("category"):
            entries = ", ".join(
                '"{}" [{}]'.format(r["name"], r["unit"])
                for _, r in grp.iterrows()
            )
            lines.append("  [{}] {}".format(cat, entries))

    macro_inds = _q("SELECT id, name, unit FROM macro_indicators ORDER BY name")
    if not macro_inds.empty:
        vals = " | ".join(
            '{} (id={}, unit={})'.format(r["name"], r["id"], r["unit"])
            for _, r in macro_inds.iterrows()
        )
        lines.append("\nmacro_indicators: " + vals)

    countries = _q("SELECT id, name FROM countries ORDER BY name LIMIT 20")
    if not countries.empty:
        vals = ", ".join("{} (id={})".format(r["name"], r["id"]) for _, r in countries.iterrows())
        lines.append("\ncountries (sample): " + vals)

    comp_df = _q("SELECT id, name FROM jet_engine_components ORDER BY name")
    if not comp_df.empty:
        vals = ", ".join("{} (id={})".format(r["name"], r["id"]) for _, r in comp_df.iterrows())
        lines.append("\njet_engine_components: " + vals)

    # ── Large tables: schema only ──────────────────────────────────────────────
    lines.append("""
price_snapshots (id, commodity_id, price [USD], fetched_at):
  Latest snapshot per commodity: WHERE id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)

price_history (id, commodity_id, date [YYYY-MM-DD], open, high, low, close [USD], volume):
  Weekly OHLC data from 2021-04-19 to present. ~262 rows per commodity.
  Date range query: WHERE date >= DATE('now', '-N days') or '-N months' or '-N years'
  1-year change: compare latest snapshot price vs price_history where date <= DATE('now','-1 year')

assumptions (88 rows): assumption_id, project_id, project_name, category, assumption_type [boolean|economic|material],
  location [Internal|External], assumption [text], ticker, event_date, price_per_unit, currency, unit, qty, total_cost,
  ai_classification [Assumption|Risk|Assumption+Risk], ai_risk_level [High|Medium|Low|N/A],
  ai_rationale [text], ai_assessed_at [timestamp]
  JOIN to commodities via ticker to get live prices. Projects: Engine Casing, Fan blade manufacturing,
  Compressor assembly, Chamber fabrication, Turbine manufacturing, Nozzle assembly, Bearing assembly, Fuel system components.

projects (8 rows): project_id, project_name, customer_name, budget_gbp, budget_threshold_pct,
  confidence_score [0-100], status [Active|Monitor|At Risk|On Hold|Complete], description, created_at, updated_at
  JOIN to assumptions via project_id to get all costs and risks for a project.

project_audit_log: id, project_id, timestamp, field_name, old_value, new_value, user, change_reason
  Tracks changes to project confidence, budget etc. over time. Query for trends:
  SELECT timestamp, new_value FROM project_audit_log WHERE project_id=X AND field_name='confidence_score' ORDER BY timestamp

assumption_tracker: assumption_id [ASXXX], title, category, owner, description, baseline_value, current_value,
  unit, internal_drift_pct, external_drift_pct, confidence_score, last_review_date, review_interval_days,
  dependencies, status [Open|Monitor|Mitigated|Closed], created_at, updated_at
  Internal project assumptions with drift tracking and confidence scoring.

assumption_audit_log: id, timestamp, assumption_id, action [CREATE|UPDATE|DELETE],
  field_name, old_value, new_value, user, change_reason

component_materials (component_id, commodity_id, weight):
  Links jet_engine_components to commodities. Use to find which materials are in a component.

macro_data (id, country_id, indicator_id, value, year, source):
  Annual World Bank macro data. Latest year: SELECT MAX(year) FROM macro_data WHERE country_id=X AND indicator_id=Y

commodity_relationships (id, from_commodity_id, to_commodity_id, relationship_type_id, strength, notes)
relationship_types (id, name)
macro_commodity_relationships (id, indicator_id, commodity_id, relationship_type_id, direction, strength, notes)""")

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
