import sqlite3
import subprocess
import sys
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path

_ROOT = str(Path(__file__).parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.shared import (
    BLUE, BLUE_DIM, BLUE_DARK, GOLD, BG, CARD_BG,
    get_gbp_usd, db_query, inject_theme,
)

DB_PATH = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"

st.set_page_config(page_title="Cost Dashboard", page_icon="📊", layout="wide")
inject_theme("""
    [data-testid="metric-container"] {
        background-color: #0C1629; border: 1px solid #0D2040; border-radius: 6px; padding: 12px;
    }
    [data-testid="metric-container"] label { color: #1A8CBF !important; font-size: 0.75rem; }
    .stSelectbox label, .stMultiSelect label { color: #1A8CBF !important; }
    .stDataFrame { border: 1px solid #0D2040 !important; }
    div[role="radiogroup"] label { color: #4FC3F7 !important; }
""")

# ── Constants ─────────────────────────────────────────────────────────────────
PLOT_BG = "#0A0F25"
COLORS = ["#4FC3F7","#C4A44A","#60E4B8","#F06A9F","#8DA9FF","#F5A623","#7ED321","#9B59B6"]
TIMEFRAMES = {"1M":"-1 month","3M":"-3 months","6M":"-6 months","1Y":"-1 year","2Y":"-2 years","5Y":"-5 years"}

UK_NLW = {2019:8.21, 2020:8.72, 2021:8.91, 2022:9.50, 2023:10.42, 2024:11.44, 2025:12.21}

# ── DB helper (cached, dashboard-local for ttl=60) ────────────────────────────
@st.cache_data(ttl=60)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return db_query(sql, params)


if not DB_PATH.exists():
    st.error("Database not found. Run: python API_Connection_Files/run_all.py")
    st.stop()


def usd_to_gbp(usd, rate: float):
    if usd is None or pd.isna(usd): return None
    return float(usd) / rate


def fmt_gbp(usd, rate: float) -> str:
    v = usd_to_gbp(usd, rate)
    return "£{:,.2f}".format(v) if v is not None else "N/A"


def ph_to_gbp(df: pd.DataFrame, rate: float) -> pd.DataFrame:
    df = df.copy()
    for col in ("open","high","low","close"):
        if col in df.columns:
            df[col] = df[col] / rate
    return df


# ── Chart helpers ─────────────────────────────────────────────────────────────
def dark_layout(fig, title=""):
    fig.update_layout(
        title=dict(text=title, font=dict(color=BLUE, size=14)),
        paper_bgcolor=BG, plot_bgcolor=PLOT_BG,
        font=dict(color=BLUE_DIM, size=11),
        xaxis=dict(gridcolor=BLUE_DARK, zerolinecolor=BLUE_DARK, tickfont=dict(color=BLUE_DIM)),
        yaxis=dict(gridcolor=BLUE_DARK, zerolinecolor=BLUE_DARK, tickfont=dict(color=BLUE_DIM)),
        legend=dict(bgcolor=CARD_BG, bordercolor=BLUE_DARK, font=dict(color=BLUE_DIM)),
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig


def add_trend(fig, df: pd.DataFrame, name: str = "", first: bool = True, symbol: str = "£"):
    if len(df) < 5:
        return
    dates = pd.to_datetime(df["date"])
    origin = dates.min()
    x = (dates - origin).dt.days.values.astype(float)
    y = df["close"].values.astype(float)
    coeffs = np.polyfit(x, y, 1)
    std = max((y - np.polyval(coeffs, x)).std(), 1e-6)
    last = dates.max()
    fut = pd.date_range(last + pd.Timedelta(days=7), periods=52, freq="7D")
    fx = (fut - origin).days.values.astype(float)
    fy = np.polyval(coeffs, fx)
    xs = [str(d.date()) for d in fut]
    fig.add_trace(go.Scatter(x=xs, y=fy+2*std, mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=fy-2*std, mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor="rgba(196,164,74,0.10)",
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=xs, y=fy, mode="lines",
                             name="{} trend".format(name) if name else "Trend",
                             line=dict(color=GOLD, width=1.5, dash="dash")))
    if first:
        for label, idx in [("6M", 25), ("1Y", 51)]:
            idx = min(idx, len(fut)-1)
            td = fut[idx]
            ty = float(np.polyval(coeffs, (td - origin).days))
            fig.add_annotation(x=str(td.date()), y=ty,
                               text="{}: {}{}".format(label, symbol, "{:,.2f}".format(ty)),
                               showarrow=True, arrowhead=2, arrowsize=0.8,
                               arrowcolor=GOLD, font=dict(color=GOLD, size=10),
                               bgcolor=CARD_BG, bordercolor=GOLD, borderwidth=1)
        fig.add_shape(type="line", x0=str(last.date()), x1=str(last.date()),
                      y0=0, y1=1, xref="x", yref="paper",
                      line=dict(color=BLUE_DIM, width=1, dash="dot"))
        fig.add_annotation(x=str(last.date()), y=1, xref="x", yref="paper",
                           text="Today", showarrow=False,
                           font=dict(color=BLUE_DIM, size=10), xanchor="left")


def fetch_history(selected: list, tf_offset: str, extra_cols: str = "") -> pd.DataFrame:
    cols = "c.name, ph.date, ph.close" + (", " + extra_cols if extra_cols else "")
    return q(
        "SELECT {} FROM price_history ph JOIN commodities c ON ph.commodity_id = c.id"
        " WHERE c.name IN ({}) AND ph.date >= DATE('now', '{}') ORDER BY ph.date".format(
            cols, ",".join("?"*len(selected)), tf_offset
        ),
        tuple(selected),
    )


def line_chart(ph: pd.DataFrame, selected: list, title: str,
               trend: bool = True, symbol: str = "£") -> go.Figure:
    multi = len(selected) > 1
    if multi:
        parts = []
        for name, grp in ph.groupby("name"):
            grp = grp.sort_values("date").copy()
            first = grp["close"].iloc[0]
            if first and first != 0:
                grp["close"] = grp["close"] / first * 100
            parts.append(grp)
        ph = pd.concat(parts) if parts else ph
    fig = go.Figure()
    for i, name in enumerate(selected):
        d = ph[ph["name"] == name].sort_values("date")
        fig.add_trace(go.Scatter(x=d["date"], y=d["close"], name=name, mode="lines",
                                 line=dict(color=COLORS[i % len(COLORS)], width=1.5)))
        if trend and not multi:
            add_trend(fig, d, name=name, first=True, symbol=symbol)
    label = "Indexed (start = 100) — normalized for scale comparison" if multi else title
    dark_layout(fig, label)
    return fig


# ── Section divider ───────────────────────────────────────────────────────────
def section(icon, label):
    st.markdown(
        "<div style='display:flex;align-items:center;gap:12px;margin:20px 0 12px;'>"
        "<div style='height:1px;flex:1;background:linear-gradient(90deg,{},transparent);'></div>"
        "<div style='color:{};font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;'>{} {}</div>"
        "<div style='height:1px;flex:1;background:linear-gradient(270deg,{},transparent);'></div>"
        "</div>".format(BLUE_DARK, BLUE, icon, label, BLUE_DARK),
        unsafe_allow_html=True,
    )


# ── Page key ──────────────────────────────────────────────────────────────────
def page_key(rows: list):
    with st.expander("📋 How this page is calculated", expanded=False):
        for label, explanation in rows:
            c1, c2 = st.columns([1, 3])
            c1.markdown("**{}**".format(label))
            c2.markdown(explanation)
            st.divider()


# ── JIC risk levels ───────────────────────────────────────────────────────────
JIC = [
    ("Remote Chance",         "#2A4A7F",  5.0),
    ("Highly Unlikely",       "#1A8CBF", 22.5),
    ("Unlikely",              "#60E4B8", 37.5),
    ("Realistic Possibility", "#C4A44A", 52.5),
    ("Likely or Probable",    "#F5A623", 77.5),
    ("Highly Likely",         "#FF6B35", 92.5),
    ("Almost Certain",        "#FF2222", None),
]
JIC_COLORS = {label: color for label, color, _ in JIC}
JIC_COLORS["Unknown"] = "#333355"


def jic_label(pct) -> str:
    if pct is None or pd.isna(pct): return "Unknown"
    for label, _, threshold in JIC:
        if threshold is None or pct <= threshold:
            return label
    return "Almost Certain"


def macro_risk_score(indicator: str, value) -> float:
    v = float(value) if value is not None and not pd.isna(value) else 0
    if indicator == "CPI Inflation":        return min(v * 8, 100)
    if indicator == "GDP Growth":           return max(0, min(50 - v * 10, 100))
    if indicator == "Unemployment Rate":    return min(v * 8, 100)
    if indicator == "Lending Rate":         return min(v * 7, 100)
    if indicator == "Real Interest Rate":   return max(0, min(50 - v * 5, 100))
    if indicator == "Manufacturing (% GDP)": return max(0, 60 - v * 2)
    return 50


# ── JIC risk panel (reusable) ─────────────────────────────────────────────────
def fetch_commodity_risk(cat_filter=None) -> pd.DataFrame:
    """Return 1Y price change % for metal/energy commodities, JIC-labelled."""
    if cat_filter:
        extra = "AND cat.name = ?"
        params = (cat_filter,)
    else:
        extra = "AND cat.name IN ('metal','energy')"
        params = ()
    df = q(
        """WITH latest AS (
               SELECT commodity_id, price AS current_price FROM price_snapshots
               WHERE id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
           ),
           yr_ago AS (
               SELECT ph.commodity_id, ph.close AS price_1y FROM price_history ph
               INNER JOIN (
                   SELECT commodity_id, MAX(date) AS d
                   FROM price_history WHERE date <= DATE('now','-1 year')
                   GROUP BY commodity_id
               ) t ON ph.commodity_id=t.commodity_id AND ph.date=t.d
           )
           SELECT c.name, cat.name AS category,
                  ROUND(l.current_price, 2) AS current_price,
                  ROUND(ya.price_1y, 2)     AS price_1y,
                  CASE WHEN ya.price_1y > 0
                       THEN ROUND((l.current_price - ya.price_1y) / ya.price_1y * 100, 1)
                       ELSE NULL END AS change_pct
           FROM commodities c
           JOIN categories cat ON c.category_id = cat.id
           LEFT JOIN latest l  ON l.commodity_id = c.id
           LEFT JOIN yr_ago ya ON ya.commodity_id = c.id
           WHERE 1=1 """ + extra + " ORDER BY change_pct DESC",
        params,
    )
    if not df.empty:
        df["risk_level"] = df["change_pct"].apply(jic_label)
    return df


def jic_risk_panel(df: pd.DataFrame, chart_title: str = "1Y Price Change"):
    """JIC summary cards + horizontal bar chart, coloured by risk level."""
    if df.empty:
        st.info("Not enough price history yet — run run_all.py.")
        return
    counts = df["risk_level"].value_counts()
    cols = st.columns(len(JIC))
    for col, (level, color, _) in zip(cols, reversed(JIC)):
        n = counts.get(level, 0)
        col.markdown(
            "<div style='background:{};border:2px solid {};border-radius:8px;"
            "padding:10px 6px;text-align:center;'>"
            "<div style='font-size:1.4rem;font-weight:700;color:{};'>{}</div>"
            "<div style='font-size:0.6rem;color:{};text-transform:uppercase;"
            "letter-spacing:0.05em;margin-top:2px;line-height:1.3;'>{}</div>"
            "</div>".format(CARD_BG, color, color, n, color, level),
            unsafe_allow_html=True,
        )
    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    s = df.sort_values("change_pct", ascending=False)
    fig = go.Figure(go.Bar(
        x=s["change_pct"], y=s["name"], orientation="h",
        marker_color=[JIC_COLORS[r] for r in s["risk_level"]],
        text=["{:+.1f}%".format(v) if not pd.isna(v) else "N/A" for v in s["change_pct"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>1Y change: %{x:.1f}%<extra></extra>",
    ))
    dark_layout(fig, chart_title)
    fig.update_layout(
        height=max(200, len(df) * 48),
        yaxis=dict(autorange="reversed"),
        xaxis=dict(ticksuffix="%", gridcolor=BLUE_DARK, zerolinecolor=BLUE_DIM, zerolinewidth=1.5),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Sparkline (overview only) ─────────────────────────────────────────────────
def sparkline(names: list, gbp_rate: float) -> go.Figure:
    ph = q(
        "SELECT c.name, ph.date, ph.close FROM price_history ph"
        " JOIN commodities c ON ph.commodity_id=c.id"
        " WHERE c.name IN ({}) AND ph.date >= DATE('now','-3 months')"
        " ORDER BY ph.date".format(",".join("?"*len(names))),
        tuple(names),
    )
    fig = go.Figure()
    for i, n in enumerate(names):
        d = ph[ph["name"] == n]
        fig.add_trace(go.Scatter(x=d["date"], y=d["close"]/gbp_rate, name=n, mode="lines",
                                 line=dict(color=COLORS[i % len(COLORS)], width=1.5)))
    fig.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG, height=110,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False, showgrid=False),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLUE_DIM, size=9),
                    orientation="h", x=0, y=1.2),
    )
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
import time as _time

_RUN_ALL    = Path(__file__).parent.parent / "API_Connection_Files" / "run_all.py"
_FETCH_LIVE = Path(__file__).parent.parent / "API_Connection_Files" / "fetch_live.py"
_INTERVALS  = {"30s": 30, "1 min": 60, "5 min": 300, "15 min": 900}

# Sidebar controls — always visible, never blocked
with st.sidebar:
    live_on = st.toggle(
        "Live data refresh", value=st.session_state.get("_live_on", False),
        help="Auto-fetch fresh market prices. Page stays fully interactive between fetches.",
    )
    st.session_state["_live_on"] = live_on

    if live_on:
        interval_label = st.selectbox("Refresh interval", list(_INTERVALS.keys()), index=1,
                                      key="_interval_sel")
        st.session_state["_interval_secs"] = _INTERVALS[interval_label]
    else:
        if st.button("🔄 Refresh market data", use_container_width=True):
            with st.spinner("Fetching live data — ~60s…"):
                subprocess.run([sys.executable, str(_RUN_ALL)], check=False)
            st.cache_data.clear()
            st.session_state.pop("_last_live_refresh", None)
            st.rerun()

    try:
        last = q("SELECT MAX(fetched_at) AS ts FROM price_snapshots")["ts"].iloc[0]
        last_fmt = pd.to_datetime(last).strftime("%d/%m/%Y %H:%M") if last else "No data"
    except Exception:
        last_fmt = "No data"
    st.caption(f"Last fetch: {last_fmt}")
    st.divider()
    GBP_RATE = get_gbp_usd()
    st.caption(f"GBP/USD  {GBP_RATE:.4f}  ·  Yahoo Finance / World Bank")


# ── Live refresh — background thread, no blocking, no greying out ─────────────
import threading as _threading

_FETCH_LOCK = _threading.Lock()  # prevents concurrent fetches


def _do_fetch_in_background():
    """Run fetch_live.py in a daemon thread. Page stays fully interactive."""
    if not _FETCH_LOCK.acquire(blocking=False):
        return  # a fetch is already running
    try:
        subprocess.run([sys.executable, str(_FETCH_LIVE)], capture_output=True, timeout=120)
        st.session_state["_last_live_refresh"] = _time.time()
        st.session_state["_fetching"] = False
    finally:
        _FETCH_LOCK.release()


@st.fragment(run_every="1s")
def _live_refresh_ticker():
    """Ticks every second. Launches fetch in background; never blocks the UI."""
    if not st.session_state.get("_live_on", False):
        return

    interval  = st.session_state.get("_interval_secs", 60)
    last_done = st.session_state.get("_last_live_refresh", 0)
    fetching  = st.session_state.get("_fetching", False)
    elapsed   = _time.time() - last_done
    remaining = max(0, interval - elapsed)

    if elapsed >= interval and not fetching:
        st.session_state["_fetching"] = True
        _threading.Thread(target=_do_fetch_in_background, daemon=True).start()

    label = "Fetching new prices…" if fetching else f"next refresh in {int(remaining)}s"
    st.caption(f"🔄 Live — {label}", help="Toggle off in sidebar to stop. Page shows latest cached data while fetching.")


_live_refresh_ticker()

# ── Page tabs (replaces sidebar radio) ───────────────────────────────────────
_tab_overview, _tab_metals, _tab_energy, _tab_components, _tab_fx, _tab_rel = st.tabs([
    "Overview", "Metals", "Energy", "Components", "FX & Macro", "Relationships"
])


# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with _tab_overview:
    st.markdown(
        "<div style='background:linear-gradient(135deg,#06091A 0%,#0C1629 60%,#00205B 100%);"
        "border:1px solid {};border-radius:10px;padding:24px 32px;margin-bottom:24px;'>"
        "<div style='font-size:0.75rem;color:{};letter-spacing:0.15em;text-transform:uppercase;'>Real-time market intelligence</div>"
        "<div style='font-size:2rem;font-weight:700;color:{};letter-spacing:0.04em;margin:4px 0;'>✈ Jet Engine Cost Dashboard</div>"
        "<div style='color:{};font-size:0.95rem;'>Live commodity, energy and macroeconomic data for jet engine manufacturing</div>"
        "</div>".format(BLUE_DARK, BLUE_DIM, BLUE, BLUE_DIM),
        unsafe_allow_html=True,
    )

    # ── Category overview cards ────────────────────────────────────────────────
    section("📦", "Category Overview")

    snap = q("""
        SELECT c.name, cat.name AS category, c.unit, ps.price
        FROM price_snapshots ps
        JOIN commodities c  ON ps.commodity_id = c.id
        JOIN categories cat ON c.category_id   = cat.id
        WHERE ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
        ORDER BY cat.name, c.name
    """)
    metals = snap[snap["category"] == "metal"]
    energy = snap[snap["category"] == "energy"]
    fx     = snap[snap["category"] == "fx_rate"]

    metals_risk = fetch_commodity_risk("metal")
    energy_risk = fetch_commodity_risk("energy")

    uk_macro_ov = q("""
        SELECT mi.name AS indicator, md.value, mi.unit, md.year
        FROM macro_data md
        JOIN countries co        ON md.country_id   = co.id
        JOIN macro_indicators mi ON md.indicator_id = mi.id
        WHERE co.name = 'United Kingdom'
          AND md.year = (
              SELECT MAX(year) FROM macro_data md2
              WHERE md2.country_id=md.country_id AND md2.indicator_id=md.indicator_id
          )
        ORDER BY mi.name
    """)

    def _safe_avg(df):
        vals = df["change_pct"].dropna() if not df.empty else pd.Series(dtype=float)
        return float(vals.mean()) if len(vals) else None

    def _top_risk(df):
        if df.empty: return "—"
        return df.sort_values("change_pct", ascending=False).iloc[0]["name"]

    def _card_header(icon, label, metric_label, headline, sub, level, color):
        return (
            "<div style='background:{bg};border:2px solid {c};border-radius:10px;"
            "padding:16px 18px 10px;'>"
            "<div style='font-size:0.65rem;color:{c};text-transform:uppercase;"
            "letter-spacing:0.12em;margin-bottom:6px;'>{icon} {label}</div>"
            "<div style='font-size:0.6rem;color:{dim};text-transform:uppercase;"
            "letter-spacing:0.08em;margin-bottom:3px;'>{metric_label}</div>"
            "<div style='font-size:1.7rem;font-weight:700;color:#FFFFFF;"
            "line-height:1.1;'>{headline}</div>"
            "<div style='font-size:0.7rem;color:{dim};margin-top:5px;'>{sub}</div>"
            "<div style='display:inline-block;font-size:0.6rem;color:{c};"
            "border:1px solid {c};border-radius:4px;padding:2px 6px;margin-top:8px;"
            "text-transform:uppercase;letter-spacing:0.08em;'>{level}</div>"
            "</div>"
        ).format(bg=CARD_BG, c=color, icon=icon, label=label, metric_label=metric_label,
                 headline=headline, sub=sub, dim=BLUE_DIM, level=level)

    col_m, col_e, col_f, col_mac = st.columns(4, gap="small")

    # ── Metals ────────────────────────────────────────────────────────────────
    with col_m:
        m_avg   = _safe_avg(metals_risk)
        m_level = jic_label(m_avg)
        m_color = JIC_COLORS[m_level]
        m_top   = _top_risk(metals_risk)
        m_count = len(metals)
        headline = "{:+.1f}%".format(m_avg) if m_avg is not None else "N/A"
        sub = "{} metals · Highest: {}".format(m_count, m_top)
        st.markdown(_card_header("⬡", "Metals", "Avg 1Y price change", headline, sub, m_level, m_color),
                    unsafe_allow_html=True)
        if not metals.empty:
            st.plotly_chart(sparkline(metals["name"].tolist()[:6], GBP_RATE),
                            use_container_width=True, config={"displayModeBar": False})

    # ── Energy ────────────────────────────────────────────────────────────────
    with col_e:
        e_avg   = _safe_avg(energy_risk)
        e_level = jic_label(e_avg)
        e_color = JIC_COLORS[e_level]
        e_top   = _top_risk(energy_risk)
        e_count = len(energy)
        headline = "{:+.1f}%".format(e_avg) if e_avg is not None else "N/A"
        sub = "{} commodities · Highest: {}".format(e_count, e_top)
        st.markdown(_card_header("⚡", "Energy", "Avg 1Y price change", headline, sub, e_level, e_color),
                    unsafe_allow_html=True)
        if not energy.empty:
            st.plotly_chart(sparkline(energy["name"].tolist()[:4], GBP_RATE),
                            use_container_width=True, config={"displayModeBar": False})

    # ── FX Rates ──────────────────────────────────────────────────────────────
    with col_f:
        gbpusd_row = fx[fx["name"] == "GBP/USD"]
        gbpusd_val = float(gbpusd_row["price"].iloc[0]) if not gbpusd_row.empty else GBP_RATE
        f_count    = len(fx)
        # 3M change for GBP/USD
        fx_hist = q(
            "SELECT ph.close FROM price_history ph JOIN commodities c ON ph.commodity_id=c.id"
            " WHERE c.name='GBP/USD' AND ph.date >= DATE('now','-3 months') ORDER BY ph.date"
        )
        if len(fx_hist) >= 2:
            fx_chg = (gbpusd_val - float(fx_hist["close"].iloc[0])) / float(fx_hist["close"].iloc[0]) * 100
            sub = "{} pairs · GBP/USD 3M: {:+.2f}%".format(f_count, fx_chg)
            f_level = jic_label(abs(fx_chg))
        else:
            sub = "{} GBP pairs tracked".format(f_count)
            f_level = "Unknown"
        f_color = JIC_COLORS[f_level]
        headline = "{:.4f}".format(gbpusd_val)
        st.markdown(_card_header("💱", "FX Rates  (GBP/USD)", "Live GBP/USD rate", headline, sub, f_level, f_color),
                    unsafe_allow_html=True)
        if not fx.empty:
            st.plotly_chart(sparkline(fx["name"].tolist()[:4], 1.0),
                            use_container_width=True, config={"displayModeBar": False})

    # ── UK Macro ──────────────────────────────────────────────────────────────
    with col_mac:
        cpi_row  = uk_macro_ov[uk_macro_ov["indicator"] == "CPI Inflation"]
        gdp_row  = uk_macro_ov[uk_macro_ov["indicator"] == "GDP Growth"]
        unem_row = uk_macro_ov[uk_macro_ov["indicator"] == "Unemployment Rate"]
        cpi_val  = float(cpi_row["value"].iloc[0])  if not cpi_row.empty  else None
        gdp_val  = float(gdp_row["value"].iloc[0])  if not gdp_row.empty  else None
        unem_val = float(unem_row["value"].iloc[0]) if not unem_row.empty else None
        mac_score  = macro_risk_score("CPI Inflation", cpi_val) if cpi_val is not None else 50
        mac_level  = jic_label(mac_score)
        mac_color  = JIC_COLORS[mac_level]
        headline   = "{:.1f}%".format(cpi_val) if cpi_val is not None else "N/A"
        gdp_str    = "GDP {:+.1f}%".format(gdp_val)  if gdp_val  is not None else ""
        unem_str   = "  Unem {:.1f}%".format(unem_val) if unem_val is not None else ""
        sub        = "{}{}".format(gdp_str, unem_str).strip(" · ")
        st.markdown(_card_header("📊", "UK Macro", "UK CPI inflation", headline, sub, mac_level, mac_color),
                    unsafe_allow_html=True)
        # Mini macro value grid instead of sparkline
        mac_items = []
        for ind, val in [("CPI", cpi_val), ("GDP", gdp_val), ("Unem", unem_val)]:
            if val is not None:
                mac_items.append((ind, "{:+.1f}%".format(val)))
        nlw_yr  = max(UK_NLW)
        mac_items.append(("NLW", "£{:.2f}".format(UK_NLW[nlw_yr])))
        if mac_items:
            row_html = "".join(
                "<div style='flex:1;text-align:center;padding:6px 0;'>"
                "<div style='font-size:0.85rem;font-weight:700;color:#FFFFFF;'>{}</div>"
                "<div style='font-size:0.6rem;color:{};text-transform:uppercase;'>{}</div>"
                "</div>".format(v, BLUE_DIM, k)
                for k, v in mac_items
            )
            st.markdown(
                "<div style='background:{};border-radius:0 0 8px 8px;margin-top:0;"
                "display:flex;gap:0;padding:8px 4px;'>{}</div>".format(CARD_BG, row_html),
                unsafe_allow_html=True,
            )

    # ── Commodity Risk Overview ────────────────────────────────────────────────
    section("⚠", "Commodity Risk Overview — 1 Year Price Change")
    all_risk = fetch_commodity_risk()
    jic_risk_panel(all_risk, "All Commodities — 1Y Price Change (JIC Rated)")

    page_key([
        ("Category cards","Metals/Energy: average 1Y price change across the category, JIC-rated. "
                          "FX: live GBP/USD rate with 3M change. Macro: latest UK CPI inflation, JIC-rated."),
        ("Risk panel",    "JIC-classified 1Y price change for all metal and energy commodities."),
        ("Currency",      "Commodity prices in USD converted to GBP at {:.4f}. FX shown as-is.".format(GBP_RATE)),
        ("Sparklines",    "3-month weekly closes, per-series scale."),
        ("Data sources",  "Yahoo Finance (metals, energy, FX) · World Bank API (macro)."),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# METALS
# ══════════════════════════════════════════════════════════════════════════════
with _tab_metals:
    st.markdown("# Metals")
    st.caption("Prices converted from USD to GBP at £1 = ${:.4f}".format(GBP_RATE))

    metals_risk = fetch_commodity_risk("metal")

    # ── Latest price cards ────────────────────────────────────────────────────
    section("💰", "Latest Prices")
    _m_snap = q("""
        SELECT c.name, c.unit, ps.price AS usd_price
        FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id = c.id
        WHERE c.category_id = (SELECT id FROM categories WHERE name = 'metal')
          AND ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
        ORDER BY c.name
    """)
    _m_risk_map = (
        {r["name"]: {"change_pct": r["change_pct"], "risk_level": r["risk_level"]}
         for _, r in metals_risk.iterrows()}
        if not metals_risk.empty else {}
    )
    _m_cards = []
    for _, row in _m_snap.iterrows():
        gbp     = row["usd_price"] / GBP_RATE if row["usd_price"] else None
        risk    = _m_risk_map.get(row["name"], {})
        pct     = risk.get("change_pct", None)
        level   = risk.get("risk_level", "Unknown") if risk else "Unknown"
        color   = JIC_COLORS.get(level, "#333355")
        chg_str = "{:+.1f}% vs 1Y ago".format(pct) if pct is not None and not pd.isna(pct) else "No 1Y data"
        price_str = "£{:,.2f}".format(gbp) if gbp else "N/A"
        _m_cards.append((row["name"], price_str, chg_str, row["unit"], level, color))

    for _row_start in range(0, len(_m_cards), 4):
        _row_items = _m_cards[_row_start:_row_start + 4]
        _cols = st.columns(len(_row_items))
        for _col, (name, price, chg, unit, level, color) in zip(_cols, _row_items):
            _col.markdown(
                "<div style='background:{bg};border:2px solid {c};border-radius:8px;"
                "padding:14px 16px;margin-bottom:8px;'>"
                "<div style='font-size:0.6rem;color:{c};text-transform:uppercase;"
                "letter-spacing:0.1em;margin-bottom:4px;'>{level}</div>"
                "<div style='font-size:1.3rem;font-weight:700;color:#FFFFFF;'>{price}</div>"
                "<div style='font-size:0.78rem;color:{dim};margin-top:2px;'>{name}</div>"
                "<div style='font-size:0.65rem;color:#555577;margin-top:2px;'>{chg} · {unit}</div>"
                "</div>".format(bg=CARD_BG, c=color, dim=BLUE_DIM,
                                level=level, price=price, name=name, chg=chg, unit=unit),
                unsafe_allow_html=True,
            )
    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    section("⚠", "Metals Risk — 1 Year Price Change")
    jic_risk_panel(metals_risk, "Metals — 1Y Price Change (JIC Rated)")

    section("📈", "Price History")
    metals_list = q(
        "SELECT name FROM commodities"
        " WHERE category_id=(SELECT id FROM categories WHERE name='metal') ORDER BY name"
    )["name"].tolist()
    selected = st.multiselect("Select metals", metals_list, default=metals_list[:3])
    tf = st.radio("Time frame", list(TIMEFRAMES), index=3, horizontal=True,
                  key="metals_tf", label_visibility="collapsed")

    if selected:
        ph = fetch_history(selected, TIMEFRAMES[tf])
        ph = ph_to_gbp(ph, GBP_RATE)
        if ph.empty:
            st.info("No historical data yet — run run_all.py.")
        else:
            if len(selected) == 1:
                st.caption("Trend projection 6M and 1Y ahead (dashed gold line).")
            else:
                st.caption("Multiple metals — normalized to 100 at start of period for scale comparison.")
            st.plotly_chart(line_chart(ph, selected, "Weekly Close (GBP, £)"), use_container_width=True)

    with st.expander("Latest snapshots (GBP)"):
        snap = q("""SELECT c.name, ps.price AS usd_price, c.unit, ps.fetched_at
                    FROM price_snapshots ps JOIN commodities c ON ps.commodity_id=c.id
                    WHERE c.category_id=(SELECT id FROM categories WHERE name='metal')
                    AND ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)""")
        snap["Price (GBP)"] = snap["usd_price"].apply(lambda x: usd_to_gbp(x, GBP_RATE))
        st.dataframe(snap[["name", "Price (GBP)", "unit", "fetched_at"]],
                     use_container_width=True, hide_index=True,
                     column_config={"Price (GBP)": st.column_config.NumberColumn(format="£%.2f")})

    page_key([
        ("Risk panel",      "1Y price change per metal, coloured by JIC level. "
                            "Positive = metal costs more than a year ago."),
        ("Currency",        "USD prices divided by GBPUSD rate ({:.4f}).".format(GBP_RATE)),
        ("Single selection","Absolute GBP price with OLS linear trend projected 52 weeks forward."),
        ("Multi-selection", "Re-based to 100 at period start — y-axis is % change, not price."),
        ("Uncertainty band","±2 standard deviations of regression residuals around the trend line."),
        ("Tickers",         "ALI=F Aluminum · HRC=F Steel (HRC) · HG=F Copper · "
                            "PL=F Platinum · PA=F Palladium · GC=F Gold · SI=F Silver"),
        ("Source",          "Yahoo Finance weekly OHLC via yfinance, up to 5 years of history."),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# ENERGY
# ══════════════════════════════════════════════════════════════════════════════
with _tab_energy:
    st.markdown("# Energy")
    st.caption("Prices converted from USD to GBP at £1 = ${:.4f}".format(GBP_RATE))

    energy_risk = fetch_commodity_risk("energy")

    # ── Latest price cards ────────────────────────────────────────────────────
    section("💰", "Latest Prices")
    _e_snap = q("""
        SELECT c.name, c.unit, ps.price AS usd_price
        FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id = c.id
        WHERE c.category_id = (SELECT id FROM categories WHERE name = 'energy')
          AND ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
        ORDER BY c.name
    """)
    _e_risk_map = (
        {r["name"]: {"change_pct": r["change_pct"], "risk_level": r["risk_level"]}
         for _, r in energy_risk.iterrows()}
        if not energy_risk.empty else {}
    )
    _e_cards = []
    for _, row in _e_snap.iterrows():
        gbp     = row["usd_price"] / GBP_RATE if row["usd_price"] else None
        risk    = _e_risk_map.get(row["name"], {})
        pct     = risk.get("change_pct", None)
        level   = risk.get("risk_level", "Unknown") if risk else "Unknown"
        color   = JIC_COLORS.get(level, "#333355")
        chg_str = "{:+.1f}% vs 1Y ago".format(pct) if pct is not None and not pd.isna(pct) else "No 1Y data"
        price_str = "£{:,.2f}".format(gbp) if gbp else "N/A"
        _e_cards.append((row["name"], price_str, chg_str, row["unit"], level, color))

    for _row_start in range(0, len(_e_cards), 3):
        _row_items = _e_cards[_row_start:_row_start + 3]
        _cols = st.columns(len(_row_items))
        for _col, (name, price, chg, unit, level, color) in zip(_cols, _row_items):
            _col.markdown(
                "<div style='background:{bg};border:2px solid {c};border-radius:8px;"
                "padding:14px 16px;margin-bottom:8px;'>"
                "<div style='font-size:0.6rem;color:{c};text-transform:uppercase;"
                "letter-spacing:0.1em;margin-bottom:4px;'>{level}</div>"
                "<div style='font-size:1.3rem;font-weight:700;color:#FFFFFF;'>{price}</div>"
                "<div style='font-size:0.78rem;color:{dim};margin-top:2px;'>{name}</div>"
                "<div style='font-size:0.65rem;color:#555577;margin-top:2px;'>{chg} · {unit}</div>"
                "</div>".format(bg=CARD_BG, c=color, dim=BLUE_DIM,
                                level=level, price=price, name=name, chg=chg, unit=unit),
                unsafe_allow_html=True,
            )
    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    section("⚠", "Energy Risk — 1 Year Price Change")
    jic_risk_panel(energy_risk, "Energy — 1Y Price Change (JIC Rated)")

    section("📈", "Price History")
    energy_list = q(
        "SELECT name FROM commodities"
        " WHERE category_id=(SELECT id FROM categories WHERE name='energy') ORDER BY name"
    )["name"].tolist()
    selected = st.multiselect("Select commodities", energy_list, default=energy_list[:3])
    tf = st.radio("Time frame", list(TIMEFRAMES), index=3, horizontal=True,
                  key="energy_tf", label_visibility="collapsed")

    if selected:
        ph = fetch_history(selected, TIMEFRAMES[tf], extra_cols="ph.open, ph.high, ph.low")
        ph = ph_to_gbp(ph, GBP_RATE)
        if ph.empty:
            st.info("No historical data yet — run run_all.py.")
        else:
            if len(selected) == 1:
                d = ph.sort_values("date")
                fig = go.Figure(go.Candlestick(
                    x=d["date"], open=d["open"], high=d["high"],
                    low=d["low"], close=d["close"], name=selected[0],
                    increasing_line_color=BLUE, decreasing_line_color="#F06A9F",
                ))
                add_trend(fig, d, name=selected[0], first=True, symbol="£")
                dark_layout(fig, "{} — Weekly OHLC (GBP)".format(selected[0]))
                st.caption("Trend projection 6M and 1Y ahead (dashed gold line).")
            else:
                fig = line_chart(ph, selected, "Weekly Close (GBP, £)")
                st.caption("Multiple commodities — normalized to 100 for scale comparison.")
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("Latest snapshots (GBP)"):
        snap = q("""SELECT c.name, ps.price AS usd_price, c.unit, ps.fetched_at
                    FROM price_snapshots ps JOIN commodities c ON ps.commodity_id=c.id
                    WHERE c.category_id=(SELECT id FROM categories WHERE name='energy')
                    AND ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)""")
        snap["Price (GBP)"] = snap["usd_price"].apply(lambda x: usd_to_gbp(x, GBP_RATE))
        st.dataframe(snap[["name", "Price (GBP)", "unit", "fetched_at"]],
                     use_container_width=True, hide_index=True,
                     column_config={"Price (GBP)": st.column_config.NumberColumn(format="£%.2f")})

    page_key([
        ("Risk panel",      "1Y price change per energy commodity, JIC-classified."),
        ("Currency",        "USD futures prices divided by GBPUSD rate ({:.4f}).".format(GBP_RATE)),
        ("Single selection","Candlestick (weekly OHLC) + OLS trend projected 52 weeks forward."),
        ("Multi-selection", "Line chart normalised to 100 — energy commodities span very different ranges."),
        ("Tickers",         "CL=F WTI Crude Oil · BZ=F Brent Crude Oil · NG=F Natural Gas · "
                            "RB=F Gasoline (RBOB) · HO=F Heating Oil · MTF=F Coal (Rotterdam)"),
        ("Source",          "Yahoo Finance NYMEX/ICE futures via yfinance."),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════
with _tab_components:
    st.markdown("# Engine Components at Risk")
    st.caption("Risk score = average 1-year price change across a component's raw materials. "
               "Classification uses UK Joint Intelligence Committee probability language.")

    risk_df = q("""
        WITH latest AS (
            SELECT commodity_id, price AS current_price FROM price_snapshots
            WHERE id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
        ),
        yr_ago AS (
            SELECT ph.commodity_id, ph.close AS price_1y FROM price_history ph
            INNER JOIN (
                SELECT commodity_id, MAX(date) AS d
                FROM price_history WHERE date <= DATE('now','-1 year')
                GROUP BY commodity_id
            ) t ON ph.commodity_id=t.commodity_id AND ph.date=t.d
        )
        SELECT jec.name AS component, c.name AS material, c.unit,
               ROUND(l.current_price, 2) AS current_price,
               ROUND(ya.price_1y, 2)     AS price_1y,
               CASE WHEN ya.price_1y > 0
                    THEN ROUND((l.current_price - ya.price_1y) / ya.price_1y * 100, 1)
                    ELSE NULL END AS change_pct
        FROM component_materials cm
        JOIN jet_engine_components jec ON cm.component_id = jec.id
        JOIN commodities c             ON cm.commodity_id = c.id
        LEFT JOIN latest l  ON l.commodity_id  = c.id
        LEFT JOIN yr_ago ya ON ya.commodity_id = c.id
        ORDER BY jec.name, c.name
    """)

    if risk_df.empty:
        st.info("No data yet — run run_all.py.")
    else:
        risk_df["risk_level"] = risk_df["change_pct"].apply(jic_label)
        comp_agg = (
            risk_df.groupby("component")["change_pct"].mean()
            .reset_index().rename(columns={"change_pct": "avg_change"})
        )
        comp_agg["risk_level"] = comp_agg["avg_change"].apply(jic_label)
        comp_agg = comp_agg.sort_values("avg_change", ascending=False)

        comp_counts = comp_agg["risk_level"].value_counts()
        cols = st.columns(len(JIC))
        for col, (level, color, _) in zip(cols, reversed(JIC)):
            n = comp_counts.get(level, 0)
            col.markdown(
                "<div style='background:{};border:2px solid {};border-radius:8px;"
                "padding:10px 6px;text-align:center;'>"
                "<div style='font-size:1.4rem;font-weight:700;color:{};'>{}</div>"
                "<div style='font-size:0.6rem;color:{};text-transform:uppercase;"
                "letter-spacing:0.05em;margin-top:2px;line-height:1.3;'>{}</div>"
                "</div>".format(CARD_BG, color, color, n, color, level),
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

        fig = go.Figure(go.Bar(
            x=comp_agg["avg_change"], y=comp_agg["component"], orientation="h",
            marker_color=[JIC_COLORS[r] for r in comp_agg["risk_level"]],
            text=["{:+.1f}%".format(v) if not pd.isna(v) else "N/A" for v in comp_agg["avg_change"]],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Avg 1Y change: %{x:.1f}%<extra></extra>",
        ))
        dark_layout(fig, "Component Risk — Average 1Y Material Price Change")
        fig.update_layout(height=420, yaxis=dict(autorange="reversed"),
                          xaxis=dict(ticksuffix="%", gridcolor=BLUE_DARK,
                                     zerolinecolor=BLUE_DIM, zerolinewidth=1.5))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.markdown("### Component Drilldown")
        sel_comp = st.selectbox("Select component", comp_agg["component"].tolist())

        if sel_comp:
            mat_df    = risk_df[risk_df["component"] == sel_comp]
            mat_names = mat_df["material"].tolist()
            col_left, col_right = st.columns([1, 2])

            with col_left:
                mat_sorted = mat_df.sort_values("change_pct", ascending=True)
                fig2 = go.Figure(go.Bar(
                    x=mat_sorted["change_pct"], y=mat_sorted["material"], orientation="h",
                    marker_color=[JIC_COLORS[r] for r in mat_sorted["risk_level"]],
                    text=["{:+.1f}%".format(v) if not pd.isna(v) else "N/A"
                          for v in mat_sorted["change_pct"]],
                    textposition="outside",
                    hovertemplate="<b>%{y}</b><br>1Y change: %{x:.1f}%<extra></extra>",
                ))
                dark_layout(fig2, "{} — Material 1Y Change".format(sel_comp))
                fig2.update_layout(
                    height=max(180, len(mat_names)*50),
                    xaxis=dict(ticksuffix="%", gridcolor=BLUE_DARK,
                               zerolinecolor=BLUE_DIM, zerolinewidth=1.5),
                )
                st.plotly_chart(fig2, use_container_width=True)
                st.caption("Prices in GBP at rate £1 = ${:.4f}".format(GBP_RATE))
                for _, row in mat_df.iterrows():
                    pct = row["change_pct"]
                    delta = "{:+.1f}% vs 1Y ago".format(pct) if not pd.isna(pct) else None
                    st.metric(label="{} — {}".format(row["material"], row["risk_level"]),
                              value=fmt_gbp(row["current_price"], GBP_RATE),
                              delta=delta, help=row["unit"])

            with col_right:
                ph = q(
                    "SELECT c.name, ph.date, ph.close FROM price_history ph"
                    " JOIN commodities c ON ph.commodity_id = c.id"
                    " WHERE c.name IN ({}) AND ph.date >= DATE('now','-2 years')"
                    " ORDER BY ph.date".format(",".join("?"*len(mat_names))),
                    tuple(mat_names),
                )
                if ph.empty:
                    st.info("No price history yet.")
                else:
                    ph = ph_to_gbp(ph, GBP_RATE)
                    fig3 = line_chart(ph, mat_names,
                                      "{} — Material Prices (2Y, GBP)".format(sel_comp), symbol="£")
                    st.plotly_chart(fig3, use_container_width=True)

    page_key([
        ("Risk score",    "Average 1Y price change (%) across raw materials per component."),
        ("1Y reference",  "Most recent weekly close on or before DATE('now','-1 year')."),
        ("JIC levels",    "≤5% Remote Chance · ≤22.5% Highly Unlikely · ≤37.5% Unlikely · "
                          "≤52.5% Realistic Possibility · ≤77.5% Likely or Probable · "
                          "≤92.5% Highly Likely · >92.5% Almost Certain"),
        ("Summary cards", "Count of *components* at each JIC level — matches bar chart colours."),
        ("Drilldown",     "Left: per-material 1Y change. Right: 2-year GBP price history."),
        ("Currency",      "USD → GBP at £1 = ${:.4f}.".format(GBP_RATE)),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# FX & MACRO  (includes UK Economic Climate + 12M Projections)
# ══════════════════════════════════════════════════════════════════════════════
with _tab_fx:
    st.markdown("# FX & Macroeconomic Intelligence")

    # ── UK Economic Climate ───────────────────────────────────────────────────
    section("📊", "UK Economic Climate")
    uk_macro = q("""
        SELECT mi.name AS indicator, md.value, mi.unit, md.year
        FROM macro_data md
        JOIN countries co        ON md.country_id   = co.id
        JOIN macro_indicators mi ON md.indicator_id = mi.id
        WHERE co.name = 'United Kingdom'
          AND md.year = (
              SELECT MAX(year) FROM macro_data md2
              WHERE md2.country_id=md.country_id AND md2.indicator_id=md.indicator_id
          )
        ORDER BY mi.name
    """)

    nlw_yr    = max(UK_NLW)
    nlw_val   = UK_NLW[nlw_yr]
    nlw_prev  = UK_NLW[nlw_yr - 1]
    nlw_delta = (nlw_val - nlw_prev) / nlw_prev * 100
    nlw_risk  = jic_label(nlw_delta)
    nlw_color = JIC_COLORS[nlw_risk]

    all_indicators = [
        ("UK Nat. Living Wage", "£{:.2f}/hr".format(nlw_val),
         "{:+.1f}% vs {}".format(nlw_delta, nlw_yr-1), nlw_risk, nlw_color,
         "April {} rate".format(nlw_yr))
    ]
    for _, row in uk_macro.iterrows():
        score = macro_risk_score(row["indicator"], row["value"])
        level = jic_label(score)
        color = JIC_COLORS[level]
        val   = row["value"]
        fmt   = "{:.1f} {}".format(val, row["unit"]) if val is not None and not pd.isna(val) else "N/A"
        all_indicators.append(
            (row["indicator"], fmt, "Latest: {}".format(int(row["year"])), level, color, row["unit"])
        )

    for row_start in range(0, len(all_indicators), 3):
        row_items = all_indicators[row_start:row_start+3]
        cols = st.columns(len(row_items))
        for col, (name, value, sub, level, color, _) in zip(cols, row_items):
            col.markdown(
                "<div style='background:{};border:2px solid {};border-radius:8px;padding:14px 16px;'>"
                "<div style='font-size:0.65rem;color:{};text-transform:uppercase;"
                "letter-spacing:0.1em;margin-bottom:4px;'>{}</div>"
                "<div style='font-size:1.3rem;font-weight:700;color:#FFFFFF;'>{}</div>"
                "<div style='font-size:0.75rem;color:{};margin-top:2px;'>{}</div>"
                "<div style='font-size:0.65rem;color:#555577;margin-top:2px;'>{}</div>"
                "</div>".format(CARD_BG, color, color, level, value, BLUE_DIM, name, sub),
                unsafe_allow_html=True,
            )

    st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

    # ── 12-Month Commodity Cost Projections ───────────────────────────────────
    section("📈", "12-Month Commodity Cost Projections")
    st.caption("OLS linear trend fitted to 1-year weekly history. JIC level = projected % price change.")

    commodity_list = q("""
        SELECT c.name, cat.name AS category, c.unit FROM commodities c
        JOIN categories cat ON c.category_id = cat.id
        WHERE cat.name IN ('metal','energy') ORDER BY cat.name, c.name
    """)

    proj_rows = []
    for _, crow in commodity_list.iterrows():
        hist = q(
            "SELECT ph.date, ph.close FROM price_history ph"
            " JOIN commodities c ON ph.commodity_id = c.id"
            " WHERE c.name = ? AND ph.date >= DATE('now','-1 year') ORDER BY ph.date",
            (crow["name"],),
        )
        if len(hist) < 8:
            continue
        dates   = pd.to_datetime(hist["date"])
        origin  = dates.min()
        x       = (dates - origin).dt.days.values.astype(float)
        y       = hist["close"].values.astype(float) / GBP_RATE
        coeffs  = np.polyfit(x, y, 1)
        cur_gbp = float(y[-1])
        prj_gbp = float(np.polyval(coeffs, x[-1] + 365))
        chg_pct = (prj_gbp - cur_gbp) / cur_gbp * 100 if cur_gbp else 0
        level   = jic_label(chg_pct)
        proj_rows.append({
            "Category":    crow["category"].title(),
            "Commodity":   crow["name"],
            "Now (£)":     round(cur_gbp, 2),
            "12M Est (£)": round(prj_gbp, 2),
            "Δ%":          round(chg_pct, 1),
            "Risk":        level,
            "_color":      JIC_COLORS[level],
        })

    if proj_rows:
        proj_df = pd.DataFrame(proj_rows)
        for category in ["Metal", "Energy"]:
            cat_df = proj_df[proj_df["Category"] == category].sort_values("Δ%", ascending=False)
            if cat_df.empty:
                continue
            st.markdown("**{}**".format(category))
            header = st.columns([2, 1.2, 1.2, 0.9, 1.8])
            for col, h in zip(header, ["Commodity", "Now (£)", "12M Est (£)", "Δ%", "Risk"]):
                col.markdown("<small style='color:{};'>{}</small>".format(BLUE_DIM, h),
                             unsafe_allow_html=True)
            for _, r in cat_df.iterrows():
                c1, c2, c3, c4, c5 = st.columns([2, 1.2, 1.2, 0.9, 1.8])
                color = r["_color"]
                chg   = r["Δ%"]
                arrow = "▲" if chg > 0 else "▼"
                c1.markdown(r["Commodity"])
                c2.markdown("£{:,.2f}".format(r["Now (£)"]))
                c3.markdown("£{:,.2f}".format(r["12M Est (£)"]))
                c4.markdown(
                    "<span style='color:{};'>{} {:.1f}%</span>".format(color, arrow, abs(chg)),
                    unsafe_allow_html=True,
                )
                c5.markdown(
                    "<span style='color:{};font-size:0.8rem;'>{}</span>".format(color, r["Risk"]),
                    unsafe_allow_html=True,
                )
            st.markdown("")
    else:
        st.info("No price history yet — run run_all.py first.")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── FX & Macro charts ─────────────────────────────────────────────────────
    section("💱", "FX Rates & World Bank Macro")
    tab_fx, tab_macro = st.tabs(["FX Rates", "Macro Indicators"])

    with tab_fx:
        fx_list = q(
            "SELECT name FROM commodities"
            " WHERE category_id=(SELECT id FROM categories WHERE name='fx_rate') ORDER BY name"
        )["name"].tolist()
        selected = st.multiselect("GBP pairs", fx_list, default=fx_list)
        tf = st.radio("Time frame", list(TIMEFRAMES), index=3, horizontal=True,
                      key="fx_tf", label_visibility="collapsed")
        if selected:
            ph = fetch_history(selected, TIMEFRAMES[tf])
            if ph.empty:
                st.info("No FX history yet — run run_all.py.")
            else:
                if len(selected) == 1:
                    st.caption("Trend projection 6M and 1Y ahead.")
                else:
                    st.caption("Normalized to 100 — GBP/JPY (~190) would otherwise flatten all other pairs.")
                st.plotly_chart(
                    line_chart(ph, selected, "GBP FX — Weekly Close", symbol=""),
                    use_container_width=True,
                )

    with tab_macro:
        countries  = q("SELECT name FROM countries ORDER BY name")["name"].tolist()
        indicators = q("SELECT name FROM macro_indicators ORDER BY name")["name"].tolist()
        col1, col2 = st.columns(2)
        default_c = [c for c in ["United Kingdom", "United States", "China"] if c in countries]
        default_i = [i for i in ["CPI Inflation", "GDP Growth"] if i in indicators]
        sel_c = col1.multiselect("Countries",  countries,  default=default_c)
        sel_i = col2.multiselect("Indicators", indicators, default=default_i)
        if sel_c and sel_i:
            macro = q(
                "SELECT co.name AS country, mi.name AS indicator, md.year, md.value, mi.unit"
                " FROM macro_data md"
                " JOIN countries co        ON md.country_id   = co.id"
                " JOIN macro_indicators mi ON md.indicator_id = mi.id"
                " WHERE co.name IN ({}) AND mi.name IN ({})"
                " ORDER BY mi.name, co.name, md.year".format(
                    ",".join("?"*len(sel_c)), ",".join("?"*len(sel_i))
                ),
                tuple(sel_c + sel_i),
            )
            if macro.empty:
                st.info("No macro data yet — run run_all.py.")
            else:
                for ind in sel_i:
                    d = macro[macro["indicator"] == ind]
                    if d.empty: continue
                    fig = go.Figure()
                    for i, country in enumerate(sel_c):
                        cd = d[d["country"] == country].sort_values("year")
                        if not cd.empty:
                            fig.add_trace(go.Bar(x=cd["year"].astype(str), y=cd["value"],
                                                 name=country, marker_color=COLORS[i % len(COLORS)]))
                    unit = d["unit"].iloc[0] if not d.empty else ""
                    dark_layout(fig, "{} [{}]".format(ind, unit))
                    fig.update_layout(barmode="group")
                    st.plotly_chart(fig, use_container_width=True)

    page_key([
        ("UK macro risk",   "Each indicator mapped to 0–100 cost-pressure score then JIC-labelled. "
                            "Higher = more risk: CPI Inflation, Unemployment Rate, Lending Rate. "
                            "Lower = more risk: GDP Growth, Real Interest Rate, Manufacturing (% GDP)."),
        ("NLW",             "National Living Wage (21+) hardcoded from GOV.UK — changes each April."),
        ("12M projections", "OLS regression on 1Y weekly closes, projected 365 days forward. "
                            "Not a financial forecast — assumes current trend continues."),
        ("FX rates",        "GBP-base pairs from Yahoo Finance. Normalised to 100 when multiple selected."),
        ("Macro data",      "World Bank Open Data API — 5 most recent annual observations per indicator. "
                            "Data typically lags 1–2 years behind current date."),
        ("Countries",       "UK, US, Australia, Canada, Japan, Germany, France, China."),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# RELATIONSHIPS
# ══════════════════════════════════════════════════════════════════════════════
with _tab_rel:
    st.markdown("# Price Relationships")
    st.caption("Economic linkages between commodities and macro indicators.")

    section("⛓", "Commodity → Commodity")
    st.dataframe(q("""
        SELECT c1.name AS from_commodity, rt.name AS relationship,
               c2.name AS to_commodity, cr.strength, cr.notes
        FROM commodity_relationships cr
        JOIN commodities c1        ON cr.from_commodity_id    = c1.id
        JOIN commodities c2        ON cr.to_commodity_id      = c2.id
        JOIN relationship_types rt ON cr.relationship_type_id = rt.id
        ORDER BY rt.name, cr.strength DESC
    """), use_container_width=True, hide_index=True)

    section("📉", "Macro Indicator → Commodity")
    st.dataframe(q("""
        SELECT mi.name AS indicator, c.name AS commodity, rt.name AS relationship,
               mcr.direction, mcr.strength, mcr.notes
        FROM macro_commodity_relationships mcr
        JOIN macro_indicators mi   ON mcr.indicator_id        = mi.id
        JOIN commodities c         ON mcr.commodity_id        = c.id
        JOIN relationship_types rt ON mcr.relationship_type_id = rt.id
        ORDER BY mi.name, mcr.strength DESC
    """), use_container_width=True, hide_index=True)

    section("🔩", "Engine Component Material Exposure")
    comp_r = q("""
        SELECT jec.name AS component, c.name AS material, ps.price AS usd_price, c.unit
        FROM component_materials cm
        JOIN jet_engine_components jec ON cm.component_id=jec.id
        JOIN commodities c             ON cm.commodity_id=c.id
        LEFT JOIN price_snapshots ps   ON ps.commodity_id=c.id
            AND ps.id=(SELECT MAX(id) FROM price_snapshots WHERE commodity_id=c.id)
        ORDER BY jec.name, c.name
    """)
    comp_r["Price (GBP)"] = comp_r["usd_price"].apply(lambda x: usd_to_gbp(x, GBP_RATE))
    st.dataframe(comp_r[["component", "material", "Price (GBP)", "unit"]],
                 use_container_width=True, hide_index=True,
                 column_config={"Price (GBP)": st.column_config.NumberColumn(format="£%.2f")})

    page_key([
        ("Commodity → Commodity", "Pre-seeded domain knowledge: energy_input, substitute, co_produced etc. "
                                  "Strength: strong / moderate / weak."),
        ("Macro → Commodity",     "Direction: positive = indicator rising pushes commodity price up."),
        ("Component exposure",    "Which raw materials each engine component depends on, with live GBP price."),
        ("Data origin",           "All relationships seeded from domain knowledge in db_setup.py — "
                                  "not calculated from price data."),
    ])
