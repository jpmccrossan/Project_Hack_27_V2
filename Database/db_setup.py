"""
Creates the SQLite database schema and seeds all static reference and relationship data.
Run this once (or re-run to reset): python Database/db_setup.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

-- ── Lookup / reference tables ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sources (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    api_url TEXT,
    requires_key INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS relationship_types (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    direction   TEXT   -- 'a_drives_b' | 'bidirectional'
);

-- ── Core entity tables ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS countries (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    iso2     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS commodities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    category_id INTEGER REFERENCES categories(id),
    ticker      TEXT,
    unit        TEXT,
    source_id   INTEGER REFERENCES sources(id),
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS macro_indicators (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    wb_code     TEXT NOT NULL UNIQUE,
    unit        TEXT,
    description TEXT,
    category_id INTEGER REFERENCES categories(id)
);

-- ── Price / data tables ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS price_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity_id INTEGER NOT NULL REFERENCES commodities(id),
    price        REAL,
    fetched_at   TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity_id INTEGER NOT NULL REFERENCES commodities(id),
    date         TEXT NOT NULL,
    year         INTEGER,
    month        TEXT,
    week         TEXT,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    UNIQUE(commodity_id, date)
);

CREATE TABLE IF NOT EXISTS macro_data (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    country_id   INTEGER NOT NULL REFERENCES countries(id),
    indicator_id INTEGER NOT NULL REFERENCES macro_indicators(id),
    year         INTEGER NOT NULL,
    value        REAL,
    fetched_at   TEXT,
    UNIQUE(country_id, indicator_id, year)
);

-- ── Relationship tables ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS commodity_relationships (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    from_commodity_id    INTEGER NOT NULL REFERENCES commodities(id),
    to_commodity_id      INTEGER NOT NULL REFERENCES commodities(id),
    relationship_type_id INTEGER NOT NULL REFERENCES relationship_types(id),
    strength             TEXT CHECK(strength IN ('strong','moderate','weak')),
    notes                TEXT
);

CREATE TABLE IF NOT EXISTS macro_commodity_relationships (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_id         INTEGER NOT NULL REFERENCES macro_indicators(id),
    commodity_id         INTEGER NOT NULL REFERENCES commodities(id),
    country_id           INTEGER REFERENCES countries(id),
    relationship_type_id INTEGER NOT NULL REFERENCES relationship_types(id),
    direction            TEXT CHECK(direction IN ('positive','negative','mixed')),
    strength             TEXT CHECK(strength IN ('strong','moderate','weak')),
    notes                TEXT
);

-- ── Projects ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS projects (
    project_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name          TEXT NOT NULL UNIQUE,
    customer_name         TEXT,
    budget_gbp            REAL DEFAULT 0,
    budget_threshold_pct  REAL DEFAULT 10,
    confidence_score      INTEGER DEFAULT 70,
    status                TEXT DEFAULT 'Active',
    description           TEXT,
    created_at            TEXT,
    updated_at            TEXT
);

CREATE TABLE IF NOT EXISTS project_audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(project_id),
    timestamp     TEXT NOT NULL,
    field_name    TEXT NOT NULL,
    old_value     TEXT,
    new_value     TEXT,
    user          TEXT DEFAULT 'system',
    change_reason TEXT
);

-- ── HPO Assumptions register ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS assumptions (
    assumption_id      INTEGER PRIMARY KEY,
    project_id         INTEGER,
    project_name       TEXT,
    category           TEXT,
    assumption_type    TEXT,
    location           TEXT,
    assumption         TEXT,
    ticker             TEXT,
    event_date         TEXT,
    price_per_unit     REAL,
    currency           TEXT,
    unit               TEXT,
    qty                REAL,
    total_cost         REAL,
    updated_at         TEXT,
    ai_classification  TEXT,
    ai_risk_level      TEXT,
    ai_rationale       TEXT,
    ai_assessed_at     TEXT
);

-- ── Assumption tracker & audit ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS assumption_tracker (
    assumption_id         TEXT PRIMARY KEY,
    project_name          TEXT,
    title                 TEXT NOT NULL,
    category              TEXT NOT NULL,
    owner                 TEXT NOT NULL,
    description           TEXT,
    baseline_value        REAL,
    current_value         REAL,
    unit                  TEXT,
    internal_drift_pct    REAL DEFAULT 0,
    external_drift_pct    REAL DEFAULT 0,
    confidence_score      INTEGER DEFAULT 50,
    last_review_date      TEXT,
    review_interval_days  INTEGER DEFAULT 30,
    dependencies          TEXT,
    status                TEXT DEFAULT 'Open',
    created_at            TEXT,
    updated_at            TEXT,
    ai_classification     TEXT,
    ai_risk_level         TEXT,
    ai_rationale          TEXT,
    ai_assessed_at        TEXT
);

CREATE TABLE IF NOT EXISTS assumption_audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    assumption_id TEXT NOT NULL,
    action        TEXT NOT NULL,
    field_name    TEXT,
    old_value     TEXT,
    new_value     TEXT,
    user          TEXT DEFAULT 'system',
    change_reason TEXT
);

-- ── Jet engine context ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jet_engine_components (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS component_materials (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id INTEGER NOT NULL REFERENCES jet_engine_components(id),
    commodity_id INTEGER NOT NULL REFERENCES commodities(id),
    notes        TEXT,
    UNIQUE(component_id, commodity_id)
);
"""

# ── Seed data ─────────────────────────────────────────────────────────────────

SOURCES = [
    ("Yahoo Finance",  "https://finance.yahoo.com",          0),
    ("World Bank",     "https://api.worldbank.org/v2/",       0),
    ("ONS",            "https://api.ons.gov.uk/",             0),
]

CATEGORIES = [
    ("metal",          "Physical metals used in manufacturing"),
    ("energy",         "Energy commodities affecting production costs"),
    ("fx_rate",        "Foreign exchange rates relative to GBP"),
    ("macro_economic", "Country-level macroeconomic indicators"),
]

RELATIONSHIP_TYPES = [
    ("energy_input",       "Energy commodity is a direct production input for the target", "a_drives_b"),
    ("currency_risk",      "FX movement directly affects GBP purchase cost of target",     "a_drives_b"),
    ("demand_driver",      "Macroeconomic indicator drives demand for the commodity",       "a_drives_b"),
    ("price_correlated",   "Prices historically move together",                            "bidirectional"),
    ("inverse_correlated", "Prices historically move in opposite directions",              "bidirectional"),
    ("supply_linked",      "Shared supply chain or production inputs",                     "bidirectional"),
]

COUNTRIES = [
    ("United Kingdom", "GB"),
    ("United States",  "US"),
    ("Australia",      "AU"),
    ("Canada",         "CA"),
    ("Japan",          "JP"),
    ("Germany",        "DE"),
    ("France",         "FR"),
    ("China",          "CN"),
]

# (name, category, ticker, unit, source, notes)
COMMODITIES = [
    # Metals
    ("Aluminum",       "metal",   "ALI=F", "USD per lb",        "Yahoo Finance", "Fan cases, compressor housings"),
    ("Steel (HRC)",    "metal",   "HRC=F", "USD per short ton",  "Yahoo Finance", "Shafts, structural components"),
    ("Copper",         "metal",   "HG=F",  "USD per lb",         "Yahoo Finance", "Wiring, heat exchangers"),
    ("Platinum",       "metal",   "PL=F",  "USD per troy oz",    "Yahoo Finance", "Sensors, ignition systems"),
    ("Palladium",      "metal",   "PA=F",  "USD per troy oz",    "Yahoo Finance", "Catalytic/sensor components"),
    ("Gold",           "metal",   "GC=F",  "USD per troy oz",    "Yahoo Finance", "Corrosion-resistant coatings"),
    ("Silver",         "metal",   "SI=F",  "USD per troy oz",    "Yahoo Finance", "Brazing alloys, electrical contacts"),
    # Energy
    ("WTI Crude Oil",  "energy",  "CL=F",  "USD per barrel",    "Yahoo Finance", "US oil benchmark"),
    ("Brent Crude Oil","energy",  "BZ=F",  "USD per barrel",    "Yahoo Finance", "UK/Europe oil benchmark"),
    ("Natural Gas",    "energy",  "NG=F",  "USD per MMBtu",     "Yahoo Finance", "Henry Hub benchmark"),
    ("Gasoline (RBOB)","energy",  "RB=F",  "USD per gallon",    "Yahoo Finance", "US retail fuel benchmark"),
    ("Heating Oil",    "energy",  "HO=F",  "USD per gallon",    "Yahoo Finance", "US heating/diesel benchmark"),
    ("Coal (Rotterdam)","energy", "MTF=F", "USD per tonne",     "Yahoo Finance", "European coal benchmark"),
    # FX
    ("GBP/USD",        "fx_rate", "GBPUSD=X", "USD per £1",    "Yahoo Finance", "Dollar-priced commodities"),
    ("GBP/EUR",        "fx_rate", "GBPEUR=X", "EUR per £1",    "Yahoo Finance", "European supply chain"),
    ("GBP/AUD",        "fx_rate", "GBPAUD=X", "AUD per £1",    "Yahoo Finance", "Australian materials"),
    ("GBP/CAD",        "fx_rate", "GBPCAD=X", "CAD per £1",    "Yahoo Finance", "Canadian materials"),
    ("GBP/CNY",        "fx_rate", "GBPCNY=X", "CNY per £1",    "Yahoo Finance", "Chinese manufacturing inputs"),
    ("GBP/JPY",        "fx_rate", "GBPJPY=X", "JPY per £1",    "Yahoo Finance", "Japanese precision components"),
]

# (name, wb_code, unit, description, category)
MACRO_INDICATORS = [
    ("CPI Inflation",         "FP.CPI.TOTL.ZG",  "% per annum",       "Consumer price inflation, annual %",       "macro_economic"),
    ("GDP Growth",            "NY.GDP.MKTP.KD.ZG","% per annum",       "Real GDP growth rate",                     "macro_economic"),
    ("Unemployment Rate",     "SL.UEM.TOTL.ZS",  "% of labour force", "ILO unemployment rate",                    "macro_economic"),
    ("Lending Rate",          "FR.INR.LEND",      "% per annum",       "Commercial lending interest rate",         "macro_economic"),
    ("Real Interest Rate",    "FR.INR.RINR",      "% per annum",       "Real interest rate, inflation-adjusted",   "macro_economic"),
    ("Manufacturing (% GDP)", "NV.IND.MANF.ZS",  "% of GDP",          "Manufacturing value added as share of GDP","macro_economic"),
]

JET_ENGINE_COMPONENTS = [
    ("Fan Assembly",        "Intake fan blades and disk — largest titanium/aluminium component"),
    ("Compressor",          "Low and high-pressure compressor stages"),
    ("Combustion Chamber",  "Annular combustor where fuel is burned"),
    ("Turbine Blades",      "High-pressure turbine blades — highest temperature components"),
    ("Turbine Disk",        "Disk holding turbine blades under extreme centrifugal load"),
    ("Main Shaft",          "Connects compressor and turbine stages"),
    ("Exhaust Nozzle",      "Directs and accelerates exhaust gases"),
    ("Structural Casing",   "Engine nacelle and bypass duct"),
    ("Sensors & Instruments","Temperature, pressure and position sensors throughout engine"),
    ("Electrical Systems",  "Wiring, connectors, ignition and FADEC components"),
    ("Bearings",            "Ball and roller bearings supporting rotating shafts"),
]

# (component, commodity)
COMPONENT_MATERIALS = [
    ("Fan Assembly",         "Aluminum"),
    ("Fan Assembly",         "Steel (HRC)"),
    ("Compressor",           "Aluminum"),
    ("Compressor",           "Steel (HRC)"),
    ("Compressor",           "Platinum"),
    ("Combustion Chamber",   "Platinum"),
    ("Combustion Chamber",   "Palladium"),
    ("Turbine Blades",       "Platinum"),
    ("Turbine Blades",       "Palladium"),
    ("Turbine Disk",         "Steel (HRC)"),
    ("Main Shaft",           "Steel (HRC)"),
    ("Exhaust Nozzle",       "Steel (HRC)"),
    ("Structural Casing",    "Aluminum"),
    ("Structural Casing",    "Steel (HRC)"),
    ("Sensors & Instruments","Platinum"),
    ("Sensors & Instruments","Palladium"),
    ("Sensors & Instruments","Gold"),
    ("Sensors & Instruments","Silver"),
    ("Electrical Systems",   "Copper"),
    ("Electrical Systems",   "Gold"),
    ("Electrical Systems",   "Silver"),
    ("Bearings",             "Steel (HRC)"),
    ("Bearings",             "Silver"),
]

# (from_commodity, to_commodity, relationship_type, strength, notes)
COMMODITY_RELATIONSHIPS = [
    # Energy → Metal (energy_input)
    ("Natural Gas",    "Aluminum",    "energy_input", "strong",   "Al smelting consumes ~15 MWh/tonne; NG is primary fuel"),
    ("Natural Gas",    "Steel (HRC)", "energy_input", "moderate", "Used in direct reduced iron (DRI) steelmaking"),
    ("Natural Gas",    "Copper",      "energy_input", "moderate", "Copper smelting and refining uses NG"),
    ("Coal (Rotterdam)","Steel (HRC)","energy_input", "strong",   "Coking coal is primary reductant in blast furnace"),
    ("Heating Oil",    "Aluminum",    "energy_input", "moderate", "Alternative energy source for smelters"),
    ("WTI Crude Oil",  "Aluminum",    "energy_input", "weak",     "Crude oil affects overall energy cost basket"),
    # Energy price correlations
    ("WTI Crude Oil",  "Brent Crude Oil", "price_correlated", "strong",   "Same commodity, two benchmarks — near-perfect correlation"),
    ("WTI Crude Oil",  "Heating Oil",     "price_correlated", "strong",   "Heating oil is a crude derivative"),
    ("WTI Crude Oil",  "Gasoline (RBOB)", "price_correlated", "strong",   "Gasoline is a crude derivative"),
    ("WTI Crude Oil",  "Natural Gas",     "price_correlated", "moderate", "Energy substitution and shared demand drivers"),
    # Precious metal correlations
    ("Gold",           "Silver",     "price_correlated", "moderate", "Both are inflation hedges and safe-haven assets"),
    ("Platinum",       "Palladium",  "price_correlated", "moderate", "Both used in catalytic/sensor applications"),
    ("Gold",           "Platinum",   "price_correlated", "weak",     "Both precious metals but different demand profiles"),
    # Supply linkages
    ("Copper",         "Aluminum",   "supply_linked", "weak", "Both processed in energy-intensive smelters"),
]

# (indicator, commodity, country (None=global), relationship_type, direction, strength, notes)
MACRO_COMMODITY_RELATIONSHIPS = [
    # GDP Growth drives demand
    ("GDP Growth", "Aluminum",       None, "demand_driver", "positive", "strong",   "Al demand closely tracks construction and manufacturing output"),
    ("GDP Growth", "Copper",         None, "demand_driver", "positive", "strong",   "'Dr Copper' — copper price leads global economic activity"),
    ("GDP Growth", "Steel (HRC)",    None, "demand_driver", "positive", "strong",   "Steel is core infrastructure and manufacturing input"),
    ("GDP Growth", "WTI Crude Oil",  None, "demand_driver", "positive", "moderate", "Higher growth raises energy demand"),
    ("GDP Growth", "Natural Gas",    None, "demand_driver", "positive", "moderate", "Industrial and heating demand rises with growth"),
    # Manufacturing drives metals
    ("Manufacturing (% GDP)", "Aluminum",    None, "demand_driver", "positive", "strong",   "Al is a key manufacturing input"),
    ("Manufacturing (% GDP)", "Steel (HRC)", None, "demand_driver", "positive", "strong",   "Steel is fundamental to manufacturing"),
    ("Manufacturing (% GDP)", "Copper",      None, "demand_driver", "positive", "strong",   "Copper wiring is in all manufactured goods"),
    # Inflation effects
    ("CPI Inflation", "Gold",         None, "demand_driver", "positive", "moderate", "Gold is a classic inflation hedge"),
    ("CPI Inflation", "Silver",       None, "demand_driver", "positive", "weak",     "Silver partially tracks gold as inflation hedge"),
    ("CPI Inflation", "Natural Gas",  None, "demand_driver", "positive", "moderate", "Energy prices are a major CPI component"),
    # Interest rates / lending
    ("Lending Rate",  "Gold",         None, "demand_driver", "negative", "moderate", "Higher rates raise opportunity cost of holding gold"),
    ("Lending Rate",  "Aluminum",     None, "demand_driver", "negative", "weak",     "Higher rates slow construction/manufacturing demand"),
    # Unemployment
    ("Unemployment Rate", "Steel (HRC)", None, "demand_driver", "negative", "moderate", "Lower unemployment → more construction → more steel"),
    ("Unemployment Rate", "Copper",      None, "demand_driver", "negative", "moderate", "Lower unemployment → more industrial activity"),
]


def get_id(cur, table: str, name: str) -> int:
    row = cur.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"Row not found in {table}: {name!r}")
    return row[0]


# (project_name, customer_name, budget_gbp, budget_threshold_pct, confidence_score, status, description)
PROJECTS = [
    ("Engine Casing",          "Henry Royce",       50000,  10.0, 49, "Active",  "Structural outer casing fabrication and assembly"),
    ("Fan blade manufacturing","Charles Rolls",      43000,  12.0, 68, "Active",  "Titanium fan blade manufacture and balancing"),
    ("Compressor assembly",    "Frank Whittle",      72000,   8.0, 75, "Active",  "Multi-stage compressor build and testing"),
    ("Chamber fabrication",    "Merlin A",          145000,  10.0, 81, "Monitor", "Combustion chamber high-temp alloy fabrication"),
    ("Turbine manufacturing",  "B Lancaster",       160000,  15.0, 60, "Active",  "Turbine blade casting, coating, and assembly"),
    ("Nozzle assembly",        "Hurricane Higgins",  80000,  10.0, 80, "Active",  "Exhaust nozzle precision machining and fit"),
    ("Bearing assembly",       "Victor Vulcan",      52000,   8.0, 77, "Active",  "High-speed bearing manufacture and quality control"),
    ("Fuel system components", "Avro Spencer",       84000,  12.0, 71, "Active",  "Fuel delivery system components and sealing"),
]


def seed(cur: sqlite3.Cursor) -> None:
    cur.executemany("INSERT OR IGNORE INTO sources (name, api_url, requires_key) VALUES (?,?,?)", SOURCES)
    cur.executemany("INSERT OR IGNORE INTO categories (name, description) VALUES (?,?)", CATEGORIES)
    cur.executemany("INSERT OR IGNORE INTO relationship_types (name, description, direction) VALUES (?,?,?)", RELATIONSHIP_TYPES)
    cur.executemany("INSERT OR IGNORE INTO countries (name, iso2) VALUES (?,?)", COUNTRIES)
    cur.executemany("INSERT OR IGNORE INTO jet_engine_components (name, description) VALUES (?,?)", JET_ENGINE_COMPONENTS)

    from datetime import datetime as _dt
    _now = _dt.now().isoformat()
    for name, customer, budget, threshold, confidence, status, description in PROJECTS:
        cur.execute(
            "INSERT OR IGNORE INTO projects "
            "(project_name, customer_name, budget_gbp, budget_threshold_pct, confidence_score, status, description, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, customer, budget, threshold, confidence, status, description, _now, _now),
        )

    for name, cat, ticker, unit, source, notes in COMMODITIES:
        cat_id = get_id(cur, "categories", cat)
        src_id = get_id(cur, "sources", source)
        cur.execute(
            "INSERT OR IGNORE INTO commodities (name, category_id, ticker, unit, source_id, notes) VALUES (?,?,?,?,?,?)",
            (name, cat_id, ticker, unit, src_id, notes),
        )

    for name, wb_code, unit, description, cat in MACRO_INDICATORS:
        cat_id = get_id(cur, "categories", cat)
        cur.execute(
            "INSERT OR IGNORE INTO macro_indicators (name, wb_code, unit, description, category_id) VALUES (?,?,?,?,?)",
            (name, wb_code, unit, description, cat_id),
        )

    for component, commodity in COMPONENT_MATERIALS:
        comp_id = get_id(cur, "jet_engine_components", component)
        comm_id = get_id(cur, "commodities", commodity)
        cur.execute(
            "INSERT OR IGNORE INTO component_materials (component_id, commodity_id) VALUES (?,?)",
            (comp_id, comm_id),
        )

    for from_c, to_c, rel_type, strength, notes in COMMODITY_RELATIONSHIPS:
        from_id  = get_id(cur, "commodities", from_c)
        to_id    = get_id(cur, "commodities", to_c)
        type_id  = get_id(cur, "relationship_types", rel_type)
        cur.execute(
            "INSERT OR IGNORE INTO commodity_relationships (from_commodity_id, to_commodity_id, relationship_type_id, strength, notes) VALUES (?,?,?,?,?)",
            (from_id, to_id, type_id, strength, notes),
        )

    for ind_name, comm_name, country_name, rel_type, direction, strength, notes in MACRO_COMMODITY_RELATIONSHIPS:
        ind_id   = get_id(cur, "macro_indicators", ind_name)
        comm_id  = get_id(cur, "commodities", comm_name)
        type_id  = get_id(cur, "relationship_types", rel_type)
        country_id = get_id(cur, "countries", country_name) if country_name else None
        cur.execute(
            "INSERT OR IGNORE INTO macro_commodity_relationships (indicator_id, commodity_id, country_id, relationship_type_id, direction, strength, notes) VALUES (?,?,?,?,?,?,?)",
            (ind_id, comm_id, country_id, type_id, direction, strength, notes),
        )


def build():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    (DB_PATH.parent / "CSV").mkdir(exist_ok=True)
    (DB_PATH.parent / "JSON").mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    seed(cur)
    con.commit()
    con.close()
    print(f"Database created: {DB_PATH}")


if __name__ == "__main__":
    build()
