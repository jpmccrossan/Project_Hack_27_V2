import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="The Assumptionisator — Project Hack 27",
    page_icon="✈",
    layout="wide",
)

BLUE = "#4FC3F7"; BLUE_DIM = "#1A8CBF"; BLUE_DARK = "#0D2040"
GOLD = "#C4A44A"; BG = "#06091A"; CARD_BG = "#0C1629"

st.markdown("""
<style>
    .stApp { background-color: #06091A; color: #4FC3F7; }
    section[data-testid="stSidebar"] { background-color: #080C1F; }
    h1, h2, h3, h4 { color: #4FC3F7 !important; letter-spacing: 0.05em; }
    [data-testid="stSidebarNav"] a { color: #1A8CBF !important; }
    [data-testid="stSidebarNav"] a:hover { color: #4FC3F7 !important; }
    [data-testid="stSidebarNav"] span { color: #1A8CBF !important; }
</style>
""", unsafe_allow_html=True)

DB_PATH = Path(__file__).parent / "Data" / "jet_engine_costs.db"

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='background:linear-gradient(135deg,#06091A 0%,#0C1629 60%,#00205B 100%);"
    "border:1px solid {};border-radius:12px;padding:40px 48px;margin-bottom:32px;'>"
    "<div style='font-size:0.7rem;color:{};letter-spacing:0.25em;text-transform:uppercase;"
    "margin-bottom:4px;'>Project Hack 27 · Hackathon</div>"
    "<div style='font-size:2.6rem;font-weight:700;color:{};letter-spacing:0.04em;"
    "line-height:1.1;'>✈ The Assumptionisator</div>"
    "<div style='font-size:1rem;color:{};margin-top:6px;'>Jet Engine Manufacturing Cost Intelligence</div>"
    "<div style='margin-top:16px;height:1px;background:linear-gradient(90deg,{},transparent);'></div>"
    "<div style='font-size:0.85rem;color:{};margin-top:12px;max-width:640px;'>"
    "Live commodity prices, macroeconomic indicators, and HPO project assumptions "
    "for jet engine manufacturing cost analysis — built for Rolls-Royce."
    "</div>"
    "</div>".format(BLUE_DARK, GOLD, BLUE, BLUE_DIM, GOLD, BLUE_DIM),
    unsafe_allow_html=True,
)

# ── Navigation cards ──────────────────────────────────────────────────────────
col_a, col_b = st.columns(2, gap="large")

with col_a:
    st.markdown(
        "<div style='background:{};border:1px solid {};border-radius:10px;"
        "padding:28px 32px;height:100%;'>"
        "<div style='font-size:2rem;margin-bottom:10px;'>📋</div>"
        "<div style='font-size:1.2rem;font-weight:700;color:{};margin-bottom:8px;'>Assumptions Register</div>"
        "<div style='color:{};font-size:0.9rem;line-height:1.5;'>"
        "HPO project assumptions for all engine components — "
        "material costs, exchange rates, inflation and commercial risks."
        "</div>"
        "<div style='margin-top:16px;font-size:0.75rem;color:#555577;'>"
        "Engine Casing · Fan Blade · Compressor · Chamber · Turbine · Nozzle · Bearing · Fuel System"
        "</div>"
        "</div>".format(CARD_BG, BLUE_DARK, BLUE, BLUE_DIM),
        unsafe_allow_html=True,
    )
    st.page_link("pages/1_📋_Assumptions.py", label="Open Assumptions Register →",
                 use_container_width=True)

with col_b:
    st.markdown(
        "<div style='background:{};border:1px solid {};border-radius:10px;"
        "padding:28px 32px;height:100%;'>"
        "<div style='font-size:2rem;margin-bottom:10px;'>📊</div>"
        "<div style='font-size:1.2rem;font-weight:700;color:{};margin-bottom:8px;'>Cost Dashboard</div>"
        "<div style='color:{};font-size:0.9rem;line-height:1.5;'>"
        "Live metal, energy and FX prices converted to GBP. "
        "JIC risk ratings, trend projections, macro indicators "
        "and component exposure analysis."
        "</div>"
        "<div style='margin-top:16px;font-size:0.75rem;color:#555577;'>"
        "Overview · Metals · Energy · Components · FX &amp; Macro · Relationships"
        "</div>"
        "</div>".format(CARD_BG, BLUE_DARK, BLUE, BLUE_DIM),
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_📊_Cost_Dashboard.py", label="Open Cost Dashboard →",
                 use_container_width=True)

# ── Status ────────────────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:32px'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='color:{};font-size:0.75rem;text-transform:uppercase;"
    "letter-spacing:0.1em;margin-bottom:12px;'>System status</div>".format(BLUE_DIM),
    unsafe_allow_html=True,
)

sc1, sc2, sc3 = st.columns(3)
db_ok = DB_PATH.exists()

sc1.markdown(
    "<div style='background:{};border:1px solid {};border-radius:8px;"
    "padding:14px 18px;text-align:center;'>"
    "<div style='font-size:1.1rem;color:{};'>{}</div>"
    "<div style='font-size:0.7rem;color:{};margin-top:4px;text-transform:uppercase;'>Database</div>"
    "</div>".format(
        CARD_BG,
        "#00AA55" if db_ok else "#AA2200",
        "#00CC66" if db_ok else "#FF4444",
        "● Online" if db_ok else "● Offline",
        BLUE_DIM,
    ),
    unsafe_allow_html=True,
)

if db_ok:
    import sqlite3, pandas as pd
    try:
        con = sqlite3.connect(DB_PATH)
        n_snap = pd.read_sql_query("SELECT COUNT(*) AS n FROM price_snapshots", con)["n"].iloc[0]
        last   = pd.read_sql_query("SELECT MAX(fetched_at) AS ts FROM price_snapshots", con)["ts"].iloc[0]
        n_ass  = pd.read_sql_query("SELECT COUNT(*) AS n FROM assumptions", con)["n"].iloc[0]
        con.close()
        last_fmt = pd.to_datetime(last).strftime("%d/%m/%Y %H:%M") if last else "Never"
        sc2.markdown(
            "<div style='background:{};border:1px solid {};border-radius:8px;"
            "padding:14px 18px;text-align:center;'>"
            "<div style='font-size:1.1rem;color:{};'>{:,} snapshots</div>"
            "<div style='font-size:0.7rem;color:{};margin-top:4px;text-transform:uppercase;'>"
            "Last fetch: {}</div>"
            "</div>".format(CARD_BG, BLUE_DARK, BLUE, n_snap, BLUE_DIM, last_fmt),
            unsafe_allow_html=True,
        )
        sc3.markdown(
            "<div style='background:{};border:1px solid {};border-radius:8px;"
            "padding:14px 18px;text-align:center;'>"
            "<div style='font-size:1.1rem;color:{};'>{} rows</div>"
            "<div style='font-size:0.7rem;color:{};margin-top:4px;text-transform:uppercase;'>"
            "Assumptions loaded</div>"
            "</div>".format(CARD_BG, BLUE_DARK, BLUE, n_ass, BLUE_DIM),
            unsafe_allow_html=True,
        )
    except Exception:
        sc2.warning("Could not read database stats.")
else:
    sc2.markdown(
        "<div style='background:{};border:1px solid #AA2200;border-radius:8px;"
        "padding:14px 18px;text-align:center;'>"
        "<div style='font-size:0.85rem;color:#FF4444;'>Run run_all.py first</div>"
        "<div style='font-size:0.7rem;color:{};margin-top:4px;'>"
        "python API_Connection_Files/run_all.py</div>"
        "</div>".format(CARD_BG, BLUE_DIM),
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:32px'></div>", unsafe_allow_html=True)
st.caption(
    "Team: Clearly We Assumed · The Assumptionisator · Project Hack 27 · "
    "Data: Yahoo Finance · World Bank API · HPO Assumptions Register"
)
