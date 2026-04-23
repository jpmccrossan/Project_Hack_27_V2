"""
utils/shared.py — Shared constants, helpers, and utilities used across all pages.
Import from here rather than redefining in each page.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Database path ──────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"

# ── Theme colours ──────────────────────────────────────────────────────────────
BLUE      = "#4FC3F7"
BLUE_DIM  = "#1A8CBF"
BLUE_DARK = "#0D2040"
GOLD      = "#C4A44A"
BG        = "#06091A"
CARD_BG   = "#0C1629"
GREEN     = "#66BB6A"
AMBER     = "#FFA726"
RED       = "#EF5350"

# ── JIC confidence/deliverability scale (0–100) ────────────────────────────────
_JIC_THRESHOLDS: list[tuple[int, str, str]] = [
    (20,  "Critical",              RED),
    (35,  "Highly Unlikely",       RED),
    (50,  "Unlikely",              AMBER),
    (65,  "Realistic Possibility", AMBER),
    (80,  "Likely",                GREEN),
    (92,  "Highly Likely",         GREEN),
]


def jic_label(score: int) -> tuple[str, str]:
    """Return (label, colour) for a 0–100 confidence or deliverability score."""
    for threshold, label, colour in _JIC_THRESHOLDS:
        if score <= threshold:
            return label, colour
    return "Almost Certain", GREEN


# ── AI badge colours ───────────────────────────────────────────────────────────
RISK_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "High":   ("#EF5350", "#1A0000"),
    "Medium": ("#FFA726", "#1A0D00"),
    "Low":    ("#66BB6A", "#001A00"),
    "N/A":    ("#1A8CBF", "#0D2040"),
}
CLASS_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "Risk":             ("#FFA726", "#1A0D00"),
    "Assumption":       ("#4FC3F7", "#0D2040"),
    "Assumption+Risk":  ("#C4A44A", "#1A1000"),
}


def badge(text: str, color: str, bg: str) -> str:
    """Render a small coloured HTML badge."""
    return (
        f"<span style='background:{bg};color:{color};"
        f"border:1px solid {color};border-radius:4px;"
        f"padding:2px 8px;font-size:0.68rem;font-weight:700;"
        f"letter-spacing:0.05em;white-space:nowrap;'>{text}</span>"
    )


# ── Database helpers ───────────────────────────────────────────────────────────
def db_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Execute a SELECT query and return a DataFrame. Always closes the connection."""
    con = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def db_execute(sql: str, params: tuple = ()) -> None:
    """Execute a write statement (INSERT/UPDATE/DELETE)."""
    con = sqlite3.connect(DB_PATH)
    con.execute(sql, params)
    con.commit()
    con.close()


# ── GBP/USD rate (cached per Streamlit session) ────────────────────────────────
@st.cache_data(ttl=300)
def get_gbp_usd() -> float:
    """Return the latest GBP/USD rate from price_snapshots. Falls back to 1.27."""
    try:
        df = db_query(
            "SELECT ps.price FROM price_snapshots ps "
            "JOIN commodities c ON ps.commodity_id=c.id "
            "WHERE c.name IN ('GBP/USD','GBPUSD=X') ORDER BY ps.id DESC LIMIT 1"
        )
        if not df.empty:
            rate = float(df["price"].iloc[0])
            return rate if rate > 0 else 1.27
    except Exception:
        pass
    return 1.27


# ── Shared CSS injection ───────────────────────────────────────────────────────
def inject_theme(extra: str = "") -> None:
    """Inject the app-wide dark theme CSS into the current Streamlit page."""
    st.markdown(
        f"""<style>
        .stApp {{ background-color:{BG}; color:{BLUE}; }}
        section[data-testid="stSidebar"] {{ background-color:#080C1F; }}
        h1,h2,h3,h4 {{ color:{BLUE} !important; letter-spacing:0.04em; }}
        [data-testid="stMetricValue"] {{ color:#FFFFFF !important; font-size:1.3rem; }}
        [data-testid="stMetricLabel"] {{ color:{BLUE_DIM} !important; font-size:0.72rem; }}
        .stTabs [data-baseweb="tab"] {{ color:{BLUE_DIM}; }}
        .stTabs [aria-selected="true"] {{ color:{BLUE} !important; border-bottom:2px solid {BLUE}; }}
        {extra}
        </style>""",
        unsafe_allow_html=True,
    )
