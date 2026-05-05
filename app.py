import sys
import streamlit as st
from pathlib import Path
import sqlite3
import pandas as pd

_ROOT = str(Path(__file__).parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Ensure DB schema is always current — runs CREATE TABLE IF NOT EXISTS, safe every time
try:
    from Database.db_setup import build as _db_build
    _db_build()
except Exception:
    pass

st.set_page_config(
    page_title="The Assumptionisator — Project Hack 27",
    page_icon="✈",
    layout="wide",
)

BLUE = "#4FC3F7"; BLUE_DIM = "#1A8CBF"; BLUE_DARK = "#0D2040"
GOLD = "#C4A44A"; BG = "#06091A"; CARD_BG = "#0C1629"
GREEN = "#66BB6A"; AMBER = "#FFA726"; RED = "#EF5350"

st.markdown(f"""
<style>
    .stApp {{ background-color:{BG}; color:{BLUE}; }}
    section[data-testid="stSidebar"] {{ background-color:#080C1F; }}
    h1,h2,h3,h4 {{ color:{BLUE} !important; letter-spacing:0.04em; }}
    [data-testid="stSidebarNav"] a {{ color:{BLUE_DIM} !important; }}
    [data-testid="stSidebarNav"] a:hover {{ color:{BLUE} !important; }}
</style>
""", unsafe_allow_html=True)

DB_PATH = Path(__file__).parent / "Data" / "jet_engine_costs.db"

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='background:linear-gradient(135deg,#06091A 0%,#0C1629 60%,#00205B 100%);"
    f"border:1px solid {BLUE_DARK};border-radius:12px;padding:36px 48px;margin-bottom:28px;'>"
    f"<div style='font-size:0.7rem;color:{GOLD};letter-spacing:0.25em;text-transform:uppercase;"
    f"margin-bottom:4px;'>Project Hack 27 · Hackathon</div>"
    f"<div style='font-size:2.4rem;font-weight:700;color:{BLUE};letter-spacing:0.04em;"
    f"line-height:1.1;'>✈ The Assumptionisator</div>"
    f"<div style='font-size:1rem;color:{BLUE_DIM};margin-top:6px;'>"
    f"Jet Engine Manufacturing Cost Intelligence — Rolls-Royce</div>"
    f"</div>",
    unsafe_allow_html=True,
)

# ── Navigation cards ──────────────────────────────────────────────────────────
PAGES = [
    {
        "icon": "🎯",
        "title": "Deliverability",
        "desc": (
            "Portfolio overview — per-project budget vs cost, confidence scores, "
            "market drift, and composite deliverability. Log confidence reviews by role."
        ),
        "sub": "C Suite · Project Managers · Portfolio view",
        "file": "pages/0_Deliverability.py",
        "label": "Open Deliverability →",
        "color": GREEN,
    },
    {
        "icon": "📋",
        "title": "Assumptions Register",
        "desc": (
            "External market-linked cost assumptions (metals, energy, FX) with live price drift. "
            "Internal deliverability tracker (ASXXX items) with confidence, audit trail, and AI assessment."
        ),
        "sub": "External · Internal · AI Assessment",
        "file": "pages/1_Assumptions.py",
        "label": "Open Assumptions Register →",
        "color": AMBER,
    },
    {
        "icon": "📊",
        "title": "Market Cost Dashboard",
        "desc": (
            "Live commodity prices — metals, energy, FX, macro indicators. "
            "JIC risk ratings, trend charts, component exposure analysis, and economic relationships."
        ),
        "sub": "Metals · Energy · Components · FX & Macro",
        "file": "pages/2_Cost_Dashboard.py",
        "label": "Open Cost Dashboard →",
        "color": BLUE,
    },
    {
        "icon": "💬",
        "title": "AI Data Chat",
        "desc": (
            "Ask questions about costs, risks, and assumptions in plain English. "
            "The AI writes its own SQL queries, fetches live data, and reasons from real numbers."
        ),
        "sub": "Powered by Ollama · Local inference · No data leaves your machine",
        "file": "pages/3_LLM_Data_Chat.py",
        "label": "Open AI Chat →",
        "color": "#9C7AE8",
    },
]

cols = st.columns(2, gap="large")
for i, p in enumerate(PAGES):
    with cols[i % 2]:
        st.markdown(
            f"<div style='background:{CARD_BG};border:1px solid {p['color']}33;"
            f"border-left:3px solid {p['color']};border-radius:10px;"
            f"padding:24px 28px;margin-bottom:12px;min-height:140px;'>"
            f"<div style='font-size:1.8rem;margin-bottom:8px;'>{p['icon']}</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:{p['color']};margin-bottom:6px;'>"
            f"{p['title']}</div>"
            f"<div style='color:{BLUE_DIM};font-size:0.85rem;line-height:1.5;margin-bottom:10px;'>"
            f"{p['desc']}</div>"
            f"<div style='font-size:0.68rem;color:#444466;'>{p['sub']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.page_link(p["file"], label=p["label"], use_container_width=True)

# ── System status ─────────────────────────────────────────────────────────────
st.divider()
db_ok = DB_PATH.exists()

s1, s2, s3, s4 = st.columns(4)

def _status_card(col, label, value, ok=True):
    color = GREEN if ok else RED
    col.markdown(
        f"<div style='background:{CARD_BG};border:1px solid {color}33;border-radius:8px;"
        f"padding:12px 16px;text-align:center;'>"
        f"<div style='font-size:0.95rem;color:{color};font-weight:600;'>{value}</div>"
        f"<div style='font-size:0.65rem;color:{BLUE_DIM};margin-top:3px;text-transform:uppercase;"
        f"letter-spacing:0.08em;'>{label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

_status_card(s1, "Database", "● Online" if db_ok else "● Offline", db_ok)

if db_ok:
    try:
        con = sqlite3.connect(DB_PATH)
        n_snap = pd.read_sql_query("SELECT COUNT(*) AS n FROM price_snapshots", con)["n"].iloc[0]
        last   = pd.read_sql_query("SELECT MAX(fetched_at) AS ts FROM price_snapshots", con)["ts"].iloc[0]
        n_ass  = pd.read_sql_query("SELECT COUNT(*) AS n FROM assumptions", con)["n"].iloc[0]
        n_int  = pd.read_sql_query("SELECT COUNT(*) AS n FROM assumption_tracker", con)["n"].iloc[0]
        con.close()
        last_fmt = pd.to_datetime(last).strftime("%d/%m %H:%M") if last else "Never"
        _status_card(s2, "Market snapshots", f"{n_snap:,}")
        _status_card(s3, f"Last fetch — {last_fmt}", f"{n_ass} ext · {n_int} int assumptions")
    except Exception:
        _status_card(s2, "Database", "Read error", ok=False)
else:
    _status_card(s2, "Market data", "Run run_all.py first", ok=False)
    _status_card(s3, "Assumptions", "No data", ok=False)

try:
    import requests
    r = requests.get("http://localhost:11434/api/tags", timeout=1)
    ollama_ok = r.status_code == 200
except Exception:
    ollama_ok = False
_status_card(s4, "Ollama (AI Chat)", "● Running" if ollama_ok else "● Offline", ollama_ok)

st.divider()
st.markdown(
    f"<div style='font-size:0.65rem;color:{BLUE_DIM};text-transform:uppercase;"
    f"letter-spacing:0.1em;margin-bottom:10px;'>Quick access</div>",
    unsafe_allow_html=True,
)

SHORTCUTS = [
    ("🎯 Portfolio overview",         "pages/0_Deliverability.py"),
    ("✏️ Log a confidence review",     "pages/0_Deliverability.py"),
    ("🌍 External market costs",       "pages/1_Assumptions.py"),
    ("🏢 Internal tracker",            "pages/1_Assumptions.py"),
    ("🤖 AI risk assessment",          "pages/1_Assumptions.py"),
    ("📈 Metals prices",               "pages/2_Cost_Dashboard.py"),
    ("⚡ Energy prices",               "pages/2_Cost_Dashboard.py"),
    ("💹 FX & macro",                  "pages/2_Cost_Dashboard.py"),
    ("💬 Ask the AI a question",       "pages/3_LLM_Data_Chat.py"),
]

sc_cols = st.columns(3)
for i, (label, target) in enumerate(SHORTCUTS):
    sc_cols[i % 3].page_link(target, label=label, use_container_width=True)

st.divider()
st.caption(
    "Team: Clearly We Assumed  ·  Project Hack 27  ·  "
    "Data: Yahoo Finance · World Bank API · HPO Assumptions Register  ·  "
    "Run: python start.py"
)
