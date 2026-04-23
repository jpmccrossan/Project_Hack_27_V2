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
    st.markdown("### How Ollama accesses the database")
    st.caption(
        "There are two separate AI systems. Both run locally via Ollama — no data ever leaves the machine."
    )

    # ── Section 1: The two AI systems ────────────────────────────────────────
    st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;
            padding:16px 22px;margin-bottom:16px;'>
<div style='font-size:0.95rem;font-weight:700;color:{BLUE};margin-bottom:8px;'>
  Two separate AI systems — same Ollama, different approaches
</div>
<div style='display:flex;gap:24px;flex-wrap:wrap;'>
  <div style='flex:1;min-width:240px;border-right:1px solid {BLUE_DARK};padding-right:20px;'>
    <div style='color:{GOLD};font-weight:700;margin-bottom:4px;'>1. Risk Classifier</div>
    <div style='color:{BLUE_DIM};font-size:0.83rem;line-height:1.6;'>
      Batch job. Reads rows from the DB directly in Python, builds one prompt per row,
      sends it to Ollama, parses the JSON reply, and writes the result back to the DB.
      <br><br>Ollama <b>never touches the database</b> — Python does all the DB work.
      Ollama only receives a text prompt and returns a JSON classification.
    </div>
  </div>
  <div style='flex:1;min-width:240px;'>
    <div style='color:{GOLD};font-weight:700;margin-bottom:4px;'>2. Agentic SQL Chat</div>
    <div style='color:{BLUE_DIM};font-size:0.83rem;line-height:1.6;'>
      Conversational. Ollama is told what tables exist and writes SQL queries itself.
      Python intercepts those queries, executes them safely, and feeds the results back.
      <br><br>Ollama still <b>never touches the database directly</b> — it writes SQL as text,
      Python runs it, and sends the results back as a message.
    </div>
  </div>
</div>
</div>
    """, unsafe_allow_html=True)

    # ── Section 2: Agentic loop step by step ────────────────────────────────
    st.markdown("#### The Agentic SQL Loop — step by step")
    st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:16px 22px;'>

Every time a user sends a message, this loop runs (file: `pages/3_💬_LLM_Data_Chat.py`):

</div>
    """, unsafe_allow_html=True)

    steps = [
        ("1", BLUE, "Build the message list",
         f"The app assembles a list of messages in the OpenAI chat format: "
         f"`[system_prompt, ...conversation_history, new_user_message]`. "
         f"The system prompt is rebuilt fresh each time by `LLM/db_context.py → build_full_system_prompt()`."),
        ("2", GOLD, "Send to Ollama — Round 1",
         f"The message list is sent to Ollama's REST API at `http://localhost:11434/api/chat` "
         f"via `LLM/ollama_client.py → chat_stream()`. "
         f"Ollama streams the response token by token back to the Streamlit UI "
         f"so the user sees the reply appearing in real time. "
         f"Temperature is set to 0.2 (slightly creative but mostly deterministic)."),
        ("3", AMBER, "Extract SQL blocks",
         f"When Ollama's reply finishes, the app scans it for SQL code blocks using a regex: "
         f'`re.compile(r"```sql\\s*(.*?)\\s*```", re.DOTALL)` (file: `_SQL_RE` in the chat page). '
         f"If no SQL blocks are found, the loop ends and the reply is shown as the final answer."),
        ("4", RED, "Execute SQL safely",
         f"`LLM/db_context.py → execute_sql(query)` runs each extracted query. "
         f"**Safety check:** the function first tests whether the query starts with SELECT using "
         f'`re.compile(r"^\\s*SELECT\\b", re.IGNORECASE)`. If it does not, it returns '
         f'`"ERROR: Only SELECT queries are permitted."` without touching the database. '
         f"If it passes, it runs `pandas.read_sql_query(sql, sqlite3.connect(DB_PATH))`, "
         f"returns up to 200 rows as a formatted string, and closes the connection."),
        ("5", GREEN, "Inject results as a user message",
         f"The query results are wrapped in a new message and added to the conversation: "
         f'`"Query results:\\n\\n{{results}}\\n\\nUsing these results, answer the original question..."`. '
         f"This is sent back to Ollama as if the user replied with the data."),
        ("6", BLUE, "Round 2 … up to Round 5",
         f"Ollama receives the results and reasons from them. If its next reply contains more SQL "
         f"(e.g. it needs another table), steps 3–5 repeat. Maximum 5 rounds total (`_MAX_ROUNDS = 5`). "
         f"After 5 rounds the last response is used as the final answer regardless."),
        ("7", GOLD, "Save to session state",
         f"Only the final assistant message is appended to `st.session_state.llm_messages` "
         f"so the conversation history stays clean. Intermediate SQL-fetching rounds are "
         f"shown in expandable panels but are not saved to the conversation."),
    ]

    for num, colour, title, detail in steps:
        st.markdown(
            f"<div style='display:flex;gap:14px;align-items:flex-start;"
            f"padding:10px 0;border-bottom:1px solid {BLUE_DARK};'>"
            f"<div style='min-width:28px;height:28px;background:{colour}22;border:1px solid {colour};"
            f"border-radius:50%;display:flex;align-items:center;justify-content:center;"
            f"font-weight:700;color:{colour};font-size:0.8rem;flex-shrink:0;'>{num}</div>"
            f"<div>"
            f"<div style='font-weight:700;color:{colour};font-size:0.85rem;margin-bottom:3px;'>{title}</div>"
            f"<div style='color:{BLUE_DIM};font-size:0.82rem;line-height:1.6;'>{detail}</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    # ── Section 3: System prompt construction ────────────────────────────────
    st.markdown("#### The System Prompt — what Ollama knows before you ask anything")
    st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:16px 22px;'>

Built by `LLM/db_context.py → build_full_system_prompt()` every time the context is loaded or reloaded.
Contains five sections, assembled in Python before Ollama sees anything:

</div>
    """, unsafe_allow_html=True)

    prompt_parts = [
        ("Date & data freshness",
         "Today's date, current time, and the `MAX(fetched_at)` timestamp from `price_snapshots`. "
         "This prevents the model from using its training-data dates (e.g. saying 'Q3 2024'). "
         "The model is explicitly instructed: *never use training-data dates*."),
        ("How to query data",
         "Instructs the model to write SQL between \\`\\`\\`sql and \\`\\`\\` tags. "
         "Tells it to fix errors itself if a query fails. Reminds it only SELECT is permitted."),
        ("Currency conversion",
         "The live GBP/USD rate (fetched from `price_snapshots` in the DB at prompt-build time). "
         "The model is told to show all prices in both USD and GBP."),
        ("JIC risk scale",
         "The thresholds for the Joint Intelligence Committee scale based on 1-year % price change "
         "(Remote → Highly Unlikely → Unlikely → Realistic Possibility → Likely → Highly Likely → Almost Certain)."),
        ("Database schema",
         "Built dynamically by `_build_schema_description()`, which actually queries the live database. "
         "It reads real commodity names, IDs, and units from the DB so the model knows exactly what "
         "to write in WHERE clauses. Large tables (price_history, assumptions, etc.) get schema-only "
         "descriptions with example query patterns."),
    ]

    for title, detail in prompt_parts:
        st.markdown(
            f"<div style='padding:8px 0;border-bottom:1px solid {BLUE_DARK};'>"
            f"<span style='color:{BLUE};font-weight:700;'>{title}</span>"
            f"<span style='color:{BLUE_DIM};font-size:0.82rem;'> — {detail}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Section 4: Risk classifier detail ────────────────────────────────────
    st.markdown("#### Risk Classifier — how it works differently")
    st.markdown(f"""
<div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:10px;padding:16px 22px;'>

File: `LLM/ai_assessor.py`. This system does **not** use the agentic SQL loop.
Instead, Python does all the database work and Ollama is used only for text classification.

**Step-by-step:**

1. **Python reads rows** from `assumptions` or `assumption_tracker` using `sqlite3` directly.
2. **Python builds a prompt** per row: title, description, category, owner, baseline vs current value,
   net drift %, confidence score, status. No SQL is involved — Python already has the data.
3. **Prompt is sent to Ollama** via `LLM/ollama_client.py → chat_complete()` (non-streaming,
   temperature 0.1 for consistent output).
4. **Ollama returns JSON** in this exact format:
   `{{"classification": "Risk|Assumption|Assumption+Risk", "risk_level": "High|Medium|Low|N/A", "rationale": "..."}}`
5. **Python parses the JSON** using a regex `re.compile(r'\\{{[^{{}}]+\\}}', re.DOTALL)` to extract
   the JSON block even if the model adds surrounding text.
6. **Python writes the result back** to the database:
   `UPDATE assumptions SET ai_classification=?, ai_risk_level=?, ai_rationale=?, ai_assessed_at=?`

**Key difference from chat:** Ollama never sees the database schema, never writes SQL,
and never touches the database. Python does all data access; Ollama only classifies text.

**Auto-trigger on add:** When a new internal assumption is saved via the form,
`assess_single_tracker_row()` is called immediately (if Ollama is running) so the new
item gets classified without the user having to go to the AI Assessment tab.

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
