# Streamlit Assumptions Tracker

A lightweight project assumptions register with drift tracking, dependency mapping, confidence scoring, and persistent audit history.

## Features

- **Standardized assumption register** with categorized fields (Economic/Inflation, Commercial, Material, Third-party)
- **Internal vs external drift tracking** with dependency-aware auto-adjustments
- **Confidence scoring** (0-100) with impact weighting
- **Review-age tracking** with overdue/due-soon indicators
- **Persistent SQLite storage** — data survives app restarts
- **Complete audit history** — track every change, who made it, when, and why
- **Dependency identification** — map assumption interdependencies
- **Automatic value adjustment** — baseline values adjusted by drift and dependency factors
- **Portfolio dashboards** — KPI metrics and category drift trends
- **CSV export** — register and audit logs

## Database Schema

### `assumptions` table
Stores all assumption records with metadata and version tracking.

### `audit_log` table
Complete change history:
- Timestamp, user, assumption ID, action (CREATE/UPDATE/DELETE)
- Field-level tracking (old_value → new_value)
- Change reason for context

## Usage

### Run locally

1. Create and activate a Python environment
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   streamlit run app.py
   ```

### Tabs

- **Dashboard**: Portfolio KPIs, review status, external-driven count, category drift trends
- **Register**: Full assumptions table with all calculated fields; CSV export
- **Add/Update**: Create new assumptions; quick update confidence, review date, status
- **Audit History**: Complete change log with filters; CSV export

### Change Logging

Every create/update action captures:
- Timestamp (ISO format)
- User identifier
- Field(s) changed (old_value → new_value)
- Change reason (optional context)
- Action type (CREATE, UPDATE, DELETE)

## Demo Data

The app seeds with four sample assumptions across all four categories. Use the sidebar **"Reset & reload from DB"** button to refresh, or **"Delete all data & reset"** to clear and re-seed.

## Project Structure

- `app.py` — Main Streamlit UI
- `db.py` — SQLite database layer, CRUD, audit logging
- `tracker.db` — Persistent database file (auto-created)
- `requirements.txt` — Python dependencies

