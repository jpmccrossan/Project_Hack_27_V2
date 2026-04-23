# The Assumptionisator — Documentation

**Project Hack 27 · Rolls-Royce · Team: Clearly We Assumed**

A live cost intelligence and deliverability tracking system for jet engine manufacturing projects.

---

## What it does

Jet engine projects at Rolls-Royce rely on hundreds of assumptions about material costs, energy prices, exchange rates, supplier reliability, and team capacity. When those assumptions drift — a metal price spikes, a supplier slips — the project is at risk.

The Assumptionisator brings all of those assumptions into one place, tracks them against live market data, and lets the project team log their confidence over time. The result: a single deliverability score per project, visible to everyone from the shop floor to the C Suite.

---

## The four pages

### 🎯 Deliverability (homepage)
The top-level view. Shows every project as a card with:
- **Budget vs cost** — external market costs compared to the project budget
- **RAG status** — Green / Amber / Red based on cost vs budget ± threshold
- **Market drift** — how far commodity prices have moved from what was assumed
- **Confidence score** — the team's own assessment, averaged across reviewer roles
- **Deliverability score** — a composite 0–100 score combining all of the above

Use the **Edit Projects** tab to log a confidence review. Three roles can submit independently (General Project Working, Project Manager, C Suite) — the composite is their average.

All scores use the **JIC scale**: Critical → Highly Unlikely → Unlikely → Realistic Possibility → Likely → Highly Likely → Almost Certain.

### 📋 Assumptions Register
Two types of assumption, shown side by side:

**External — Market Costs**
Material and energy cost assumptions compared to live commodity prices. Shows:
- Assumed price (locked in at project start)
- Live market price (from Yahoo Finance)
- Drift % (how much the market has moved)
- AI classification (Risk / Assumption / Assumption+Risk) and risk level

**Internal — Deliverability Tracker**
Team-managed assumptions with ASXXX IDs. Each item tracks:
- Confidence score (reviewed periodically)
- Internal drift (team-driven changes, e.g. resource availability)
- External drift (market or regulatory changes)
- Review schedule (with Gantt chart showing overdue items)
- Owner and category

When you add a new internal assumption, the AI automatically assesses it if Ollama is running.

**AI Assessment tab**
Run Ollama to classify all assumptions — external and internal — as Risk, Assumption, or Assumption+Risk, with a risk level (High / Medium / Low) and one-sentence rationale. Results are saved to the database.

### 📊 Market Cost Dashboard
Live commodity price data from Yahoo Finance and World Bank:
- **Metals**: Aluminum, Steel, Copper, Platinum, Palladium, Gold, Silver
- **Energy**: Brent Crude, WTI Crude, Natural Gas, Heating Oil, Gasoline, Coal
- **Components**: Which metals go into which jet engine components (fan blades, turbine, etc.)
- **FX**: GBP/USD, EUR, JPY, CNY, CAD, AUD
- **Macro**: GDP, CPI, unemployment, interest rates for key supplier countries

Each commodity shows price trend, JIC risk level (based on 1-year price change), and relationship to other commodities.

### 💬 AI Data Chat
Ask questions in plain English. The AI:
1. Writes SQL queries against the live database
2. Executes them (read-only — no data can be changed)
3. Reasons from the real numbers to answer your question

Examples: *"What's the current steel price and how has it changed this year?"*  
*"Which project has the highest market drift?"*  
*"Show me all high-risk assumptions for Turbine manufacturing."*

Requires Ollama running locally. All inference is on-device — no data leaves your machine.

---

## Data sources

| Source | Data |
|--------|------|
| Yahoo Finance | Live spot prices for metals, energy, FX |
| World Bank API | Annual macro indicators (GDP, CPI, interest rates) per country |
| HPO Assumptions Register | Project cost assumptions (Matt's data) |
| Internal tracker | Team-maintained deliverability assumptions (ASXXX items) |
| Ollama | Local AI for risk assessment and natural language queries |

Data is fetched by running `API_Connection_Files/run_all.py` and stored in a single SQLite database: `Data/jet_engine_costs.db`.

---

## Database structure

All data lives in one file: `Data/jet_engine_costs.db`

| Table | Contents |
|-------|----------|
| `commodities` | Commodity names, tickers, units |
| `categories` | metal / energy / fx_rate / macro_economic |
| `price_snapshots` | Latest spot price per commodity |
| `price_history` | Weekly OHLC data from 2021 |
| `macro_indicators` | GDP, CPI, etc. |
| `macro_data` | Country × indicator × year values |
| `jet_engine_components` | Fan blade, turbine, etc. |
| `component_materials` | Which metals are in which component |
| `assumptions` | External project cost assumptions (104 rows) |
| `projects` | 8 jet engine sub-projects with budgets and confidence |
| `project_audit_log` | Field-level change history for projects |
| `assumption_tracker` | Internal ASXXX deliverability assumptions |
| `assumption_audit_log` | Change history for internal assumptions |
| `commodity_relationships` | Relationships between commodities |
| `relationship_types` | Types of commodity relationships |
| `macro_commodity_relationships` | Macro indicator → commodity relationships |

---

## Projects

| ID | Project | Customer |
|----|---------|----------|
| 1 | Engine Casing | Henry Royce |
| 2 | Fan blade manufacturing | Charles Rolls |
| 3 | Compressor assembly | B Lancaster |
| 4 | Chamber fabrication | Merlin A |
| 5 | Turbine manufacturing | Hurricane Higgins |
| 6 | Nozzle assembly | Spitfire S |
| 7 | Bearing assembly | Typhoon T |
| 8 | Fuel system components | Hawk H |

---

## How scores are calculated

**Confidence score**
Average of the latest submission from each reviewer role (General Project Working, Project Manager, C Suite). Where only one role has reviewed, that score is used.

**Deliverability score**
```
Base = confidence score
  − 20  if cost > budget + threshold  (over budget)
  − 10  if cost > budget + 60% of threshold  (at risk)
  − 10  if average market drift > ±20%
  −  5  if average market drift > ±10%
Clamped to 0–100
```

**JIC scale** (Joint Intelligence Committee — same scale used for market risk)
| Score | Label |
|-------|-------|
| 0–20  | Critical |
| 21–35 | Highly Unlikely |
| 36–50 | Unlikely |
| 51–65 | Realistic Possibility |
| 66–80 | Likely |
| 81–92 | Highly Likely |
| 93–100 | Almost Certain |

**Market drift**
Live price vs assumed price at project start, converted to USD for fair comparison. Capped at ±150% to exclude data anomalies. Averaged across all market-linked assumptions for the project.

---

## File structure

```
Project_Hack_27_V2/
├── start.py                  ← run this to launch everything
├── app.py                    ← Streamlit homepage
├── requirements.txt
├── HOW_TO_RUN.md
├── DOCUMENTATION.md          ← this file
├── pages/
│   ├── 0_🎯_Deliverability.py
│   ├── 1_📋_Assumptions.py
│   ├── 2_📊_Cost_Dashboard.py
│   └── 3_💬_LLM_Data_Chat.py
├── LLM/
│   ├── ai_assessor.py        ← Ollama risk classification
│   ├── db_context.py         ← database schema + SQL execution for chat
│   └── ollama_client.py      ← Ollama API wrapper
├── Database/
│   └── assumptions_tracker_db.py   ← CRUD for internal tracker
├── API_Connection_Files/
│   └── run_all.py            ← fetch live market data
└── Data/
    └── jet_engine_costs.db   ← single shared SQLite database
```
