"""
Technical Documentation — how the app works, data flow, AI system.
"""
import sys
from pathlib import Path

import streamlit as st

_ROOT = str(Path(__file__).parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.shared import (
    BLUE, BLUE_DIM, BLUE_DARK, GOLD, BG, CARD_BG, GREEN, AMBER, RED,
    inject_theme,
)

st.set_page_config(page_title="Technical Docs", page_icon="📖", layout="wide")
inject_theme()

st.markdown("# 📖 Technical Documentation")
st.caption("How The Assumptionisator works — data flow, architecture, and AI system.")

# ══════════════════════════════════════════════════════════════════════════════
tab_arch, tab_data, tab_ai, tab_db = st.tabs([
    "🏗 Architecture", "📡 Data Flow", "🤖 AI System", "🗄 Database Schema"
])

with tab_arch:
    st.markdown("### System Architecture")
    st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:20px 24px;'>

**Single-database, multi-page Streamlit app.** Everything reads from and writes to one SQLite file:
`Data/jet_engine_costs.db`

```
User browser
    │
    ▼
Streamlit (app.py + pages/)
    │
    ├── pages/0  Deliverability      ← portfolio health, confidence, budget vs cost
    ├── pages/1  Assumptions         ← external market costs + internal ASXXX tracker
    ├── pages/2  Market Costs        ← live commodity prices, FX, macro
    ├── pages/3  AI Chat             ← natural language queries via Ollama
    └── pages/4  Technical Docs      ← this page
    │
    ├── utils/shared.py              ← shared constants, DB helpers, JIC logic
    ├── LLM/
    │   ├── db_context.py            ← schema description + safe SQL execution
    │   ├── ollama_client.py         ← Ollama REST API wrapper
    │   └── ai_assessor.py           ← batch risk classification
    ├── Database/
    │   ├── db_setup.py              ← table creation
    │   ├── db_loader.py             ← load CSV/JSON → SQLite
    │   └── assumptions_tracker_db.py ← CRUD for internal tracker
    └── API_Connection_Files/
        ├── metal_data.py            ← Yahoo Finance metals
        ├── energy_data.py           ← Yahoo Finance energy
        ├── finance_data.py          ← Yahoo Finance FX + World Bank macro
        ├── run_all.py               ← full fetch (snapshots + history, ~60s)
        └── fetch_live.py            ← snapshot-only fetch (~15s, runs on timer)
```

</div>
    """, unsafe_allow_html=True)

    st.markdown("### Key design decisions")
    cols = st.columns(3)
    for col, title, body in [
        (cols[0], "Single database",
         "All tables — market prices, assumptions, tracker, audit logs — live in one SQLite file. "
         "This lets the AI JOIN across everything in a single query."),
        (cols[1], "No ORM",
         "Raw `sqlite3` + `pandas.read_sql_query`. Simple, fast, and the schema is small enough "
         "to fit in one screen."),
        (cols[2], "Local AI only",
         "Ollama runs models on-device. No data leaves the machine. No API keys needed. "
         "Models are swappable — gemma2, llama3.2, mistral, etc."),
    ]:
        col.markdown(
            f"<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:8px;"
            f"padding:14px 16px;height:100%;'>"
            f"<div style='font-weight:700;color:{BLUE};margin-bottom:6px;'>{title}</div>"
            f"<div style='color:{BLUE_DIM};font-size:0.85rem;line-height:1.5;'>{body}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

with tab_data:
    st.markdown("### Data flow")
    st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:20px 24px;'>

**First-time setup** (`python API_Connection_Files/run_all.py`, ~60 seconds):

```
Yahoo Finance API   →   metal_data.py    ──┐
Yahoo Finance API   →   energy_data.py   ──┤  save to Data/JSON/
Yahoo Finance API   →   finance_data.py  ──┘
World Bank API      →   finance_data.py  ──┘
                                            │
                                            ▼
                                    Database/db_loader.py
                                            │
                                            ▼
                                    jet_engine_costs.db
                                    ├── commodities
                                    ├── price_snapshots   (latest price)
                                    ├── price_history     (weekly OHLC, 5 years)
                                    ├── macro_data        (annual per country)
                                    └── fx_rates
```

**Live refresh** (`python API_Connection_Files/fetch_live.py`, ~15 seconds):
Only fetches current snapshots — no history. Runs automatically every 15 minutes when launched via `python start.py`.

**Internal data** (never fetched from APIs):
- `assumptions` — HPO project cost assumptions (loaded once from CSV)
- `assumption_tracker` — internal ASXXX items (entered via the UI)
- `projects` — project budgets and confidence (entered via the UI)
- All `_audit_log` tables — change history (written by the UI)

</div>
    """, unsafe_allow_html=True)

    st.markdown("### Commodity coverage")
    rows = [
        ("Metals",  "Aluminum (ALI=F), Steel HRC (HRC=F), Copper (HG=F), Platinum (PL=F), Palladium (PA=F), Gold (GC=F), Silver (SI=F)"),
        ("Energy",  "Brent Crude (BZ=F), WTI Crude (CL=F), Natural Gas (NG=F), Heating Oil (HO=F), Gasoline RBOB (RB=F), Coal Rotterdam (MTF=F)"),
        ("FX",      "GBP/USD, GBP/EUR, GBP/JPY, GBP/CNY, GBP/CAD, GBP/AUD"),
        ("Macro",   "GDP (current USD), CPI inflation, unemployment rate, interest rate — UK, US, EU, China, Japan"),
    ]
    for cat, items in rows:
        st.markdown(f"**{cat}:** {items}")

with tab_ai:
    st.markdown("### AI systems")

    ai1, ai2 = st.columns(2)

    with ai1:
        st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:18px 20px;'>
<div style='font-size:1rem;font-weight:700;color:{BLUE};margin-bottom:10px;'>🤖 Risk Classifier</div>

**What:** Classifies each assumption as Risk / Assumption / Assumption+Risk, assigns a risk level (High / Medium / Low / N/A), and writes a one-sentence rationale.

**How:**
1. `ai_assessor.py` builds a structured prompt per row (text, category, drift %, cost)
2. Sends to Ollama `/api/chat` with temperature 0.1
3. Parses JSON response: `{{"classification": "...", "risk_level": "...", "rationale": "..."}}`
4. Saves to `ai_classification`, `ai_risk_level`, `ai_rationale`, `ai_assessed_at` columns

**Auto-trigger:** Fires automatically when a new internal assumption is added via the form (if Ollama is running).

**Covers:** Both external assumptions table and internal tracker table.
</div>
        """, unsafe_allow_html=True)

    with ai2:
        st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:18px 20px;'>
<div style='font-size:1rem;font-weight:700;color:{BLUE};margin-bottom:10px;'>💬 Agentic SQL Chat</div>

**What:** Answers natural language questions by writing and executing its own SQL queries against the live database.

**How (agentic loop, up to 5 rounds):**
1. User asks a question
2. Model receives a system prompt containing the full DB schema + today's date
3. Model writes SQL in ` ```sql ``` ` blocks
4. App extracts and executes queries (SELECT only — no writes permitted)
5. Results are injected back as a user message: "Query results: ..."
6. Model reasons from the real data and writes its answer
7. If the answer contains more SQL, loop continues (max 5 rounds)

**Safety:** Only `SELECT` statements are allowed. Non-SELECT queries return an error string.

**Date awareness:** System prompt includes `today's date` and `last data fetch timestamp` so the model never guesses dates from training data.
</div>
        """, unsafe_allow_html=True)

    st.markdown("### JIC risk scale")
    st.markdown(
        "Used for both confidence/deliverability scores (0–100) and market price change risk. "
        "Based on the UK Joint Intelligence Committee assessment framework."
    )
    jic_cols = st.columns(7)
    jic_data = [
        ("≤20", "Critical",              RED),
        ("≤35", "Highly Unlikely",       RED),
        ("≤50", "Unlikely",              AMBER),
        ("≤65", "Realistic Possibility", AMBER),
        ("≤80", "Likely",                GREEN),
        ("≤92", "Highly Likely",         GREEN),
        (">92", "Almost Certain",        GREEN),
    ]
    for col, (band, label, colour) in zip(jic_cols, jic_data):
        col.markdown(
            f"<div style='background:{CARD_BG};border:1px solid {colour}33;"
            f"border-top:3px solid {colour};border-radius:6px;padding:10px 8px;text-align:center;'>"
            f"<div style='font-size:0.7rem;color:{colour};font-weight:700;'>{band}</div>"
            f"<div style='font-size:0.68rem;color:{BLUE_DIM};margin-top:4px;'>{label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

with tab_db:
    st.markdown("### Database tables")

    TABLE_INFO = [
        ("commodities",                "Commodity names, Yahoo tickers, units, category"),
        ("categories",                 "metal / energy / fx_rate / macro_economic"),
        ("price_snapshots",            "Latest spot price per commodity (updated on each fetch)"),
        ("price_history",              "Weekly OHLC prices, 5 years per commodity (~262 rows each)"),
        ("macro_indicators",           "GDP, CPI, unemployment, interest rate definitions"),
        ("macro_data",                 "Country × indicator × year values from World Bank"),
        ("countries",                  "Country names and IDs"),
        ("jet_engine_components",      "Fan blade, turbine, compressor, etc."),
        ("component_materials",        "Which metals go into which component (many-to-many)"),
        ("commodity_relationships",    "Commodity-to-commodity relationships (e.g. steel follows scrap)"),
        ("relationship_types",         "Types of commodity relationships"),
        ("macro_commodity_relationships", "Macro indicator → commodity directional influence"),
        ("assumptions",                "External HPO project cost assumptions (104 rows, 8 projects)"),
        ("projects",                   "8 jet engine sub-projects: budget, threshold, confidence, status"),
        ("project_audit_log",          "Field-level change history for projects (confidence, status, budget)"),
        ("assumption_tracker",         "Internal ASXXX deliverability assumptions"),
        ("assumption_audit_log",       "Change history for internal tracker assumptions"),
    ]

    for name, desc in TABLE_INFO:
        st.markdown(
            f"<div style='display:flex;gap:12px;padding:7px 0;border-bottom:1px solid {BLUE_DARK};'>"
            f"<div style='min-width:240px;font-family:monospace;color:{BLUE};font-size:0.82rem;'>{name}</div>"
            f"<div style='color:{BLUE_DIM};font-size:0.82rem;'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown(f"""
    <div style='margin-top:16px;background:{CARD_BG};border:1px solid {BLUE_DARK};
                border-radius:8px;padding:14px 18px;font-size:0.82rem;color:{BLUE_DIM};'>
    <b style='color:{BLUE};'>One database, everything in one place.</b><br>
    The AI chat can JOIN across all tables in a single query —
    e.g. project assumptions → live prices → macro indicators → audit history.
    Database path: <code style='color:#60E4B8;'>Data/jet_engine_costs.db</code>
    </div>
    """, unsafe_allow_html=True)
