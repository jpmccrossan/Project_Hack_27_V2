import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path

DB_PATH = Path(__file__).parent / "Data" / "jet_engine_costs.db"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Jet Engine Cost Dashboard",
    page_icon="✈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Rolls Royce blue theme ────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #06091A; color: #4FC3F7; }
    section[data-testid="stSidebar"] { background-color: #080C1F; }
    .stSidebar .stMarkdown { color: #4FC3F7; }

    h1, h2, h3, h4 { color: #4FC3F7 !important; letter-spacing: 0.05em; }

    [data-testid="metric-container"] {
        background-color: #0C1629;
        border: 1px solid #0D2040;
        border-radius: 6px;
        padding: 12px;
    }
    [data-testid="metric-container"] label { color: #1A8CBF !important; font-size: 0.75rem; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] { color: #4FC3F7 !important; font-size: 1.4rem; }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] { color: #C4A44A !important; }

    .stSelectbox label, .stMultiSelect label { color: #1A8CBF !important; }
    .stSelectbox div[data-baseweb="select"] > div,
    .stMultiSelect div[data-baseweb="select"] > div {
        background-color: #0C1629 !important;
        border-color: #0D2040 !important;
        color: #4FC3F7 !important;
    }

    .stTabs [data-baseweb="tab-list"] { background-color: #080C1F; border-bottom: 1px solid #0D2040; }
    .stTabs [data-baseweb="tab"] { color: #1A8CBF !important; }
    .stTabs [aria-selected="true"] { color: #4FC3F7 !important; border-bottom: 2px solid #4FC3F7 !important; }

    .stDataFrame { border: 1px solid #0D2040 !important; }
    hr { border-color: #0D2040; }

    div[role="radiogroup"] label { color: #4FC3F7 !important; }
    div[role="radiogroup"] label:hover { color: #C4A44A !important; }
</style>
""", unsafe_allow_html=True)

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_con():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


@st.cache_data(ttl=60)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    con = get_con()
    df = pd.read_sql_query(sql, con, params=params)
    con.close()
    return df


def check_db():
    if not DB_PATH.exists():
        st.error(
            "Database not found. Run:\n\n"
            "```\npython API_Connection_Files/run_all.py\n```"
        )
        st.stop()


check_db()

# ── Color palette ─────────────────────────────────────────────────────────────
BLUE      = "#4FC3F7"
BLUE_DIM  = "#1A8CBF"
BLUE_DARK = "#0D2040"
GOLD      = "#C4A44A"
BG        = "#06091A"
PLOT_BG   = "#0A0F25"
CARD_BG   = "#0C1629"

TRACE_COLORS = [
    "#4FC3F7", "#C4A44A", "#60E4B8", "#F06A9F",
    "#8DA9FF", "#F5A623", "#7ED321", "#9B59B6",
]

TIMEFRAMES = {
    "1M": "-1 month",
    "3M": "-3 months",
    "6M": "-6 months",
    "1Y": "-1 year",
    "2Y": "-2 years",
    "5Y": "-5 years",
}


def dark_layout(fig, title=""):
    fig.update_layout(
        title=dict(text=title, font=dict(color=BLUE, size=14)),
        paper_bgcolor=BG,
        plot_bgcolor=PLOT_BG,
        font=dict(color=BLUE_DIM, size=11),
        xaxis=dict(gridcolor=BLUE_DARK, zerolinecolor=BLUE_DARK, tickfont=dict(color=BLUE_DIM)),
        yaxis=dict(gridcolor=BLUE_DARK, zerolinecolor=BLUE_DARK, tickfont=dict(color=BLUE_DIM)),
        legend=dict(bgcolor=CARD_BG, bordercolor=BLUE_DARK, font=dict(color=BLUE_DIM)),
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig


def add_trend_projection(fig, df: pd.DataFrame, name: str = "", color: str = GOLD):
    """Fit linear trend on df['date']/df['close'] and project 1 year forward."""
    if len(df) < 5:
        return fig

    dates = pd.to_datetime(df["date"])
    x_num = (dates - dates.min()).dt.days.values.astype(float)
    y = df["close"].values.astype(float)

    coeffs = np.polyfit(x_num, y, 1)
    residuals = y - np.polyval(coeffs, x_num)
    std = max(residuals.std(), 1e-6)

    last_date = dates.max()
    origin = dates.min()
    future_dates = pd.date_range(last_date + pd.Timedelta(weeks=1), periods=52, freq="W")
    future_x = (future_dates - origin).days.values.astype(float)
    future_y = np.polyval(coeffs, future_x)

    xs = [str(d.date()) for d in future_dates]

    fig.add_trace(go.Scatter(
        x=xs, y=future_y + 2 * std,
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=xs, y=future_y - 2 * std,
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(196,164,74,0.12)", showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=xs, y=future_y,
        mode="lines",
        name=f"{name} trend" if name else "Trend",
        line=dict(color=color, width=1.5, dash="dash"),
    ))

    for label, idx in [("6M", 25), ("1Y", 51)]:
        idx = min(idx, len(future_dates) - 1)
        td = future_dates[idx]
        ty = float(np.polyval(coeffs, (td - origin).days))
        fig.add_annotation(
            x=str(td.date()), y=ty,
            text=f"{label}: ${ty:,.0f}",
            showarrow=True, arrowhead=2, arrowsize=0.8,
            arrowcolor=GOLD, font=dict(color=GOLD, size=10),
            bgcolor=CARD_BG, bordercolor=GOLD, borderwidth=1,
        )

    fig.add_vline(
        x=str(last_date.date()),
        line=dict(color=BLUE_DIM, width=1, dash="dot"),
        annotation_text="Today", annotation_font_color=BLUE_DIM,
        annotation_position="top right",
    )
    return fig


def timeframe_radio(key: str) -> str:
    choice = st.radio("", list(TIMEFRAMES.keys()), index=3, horizontal=True, key=key)
    return TIMEFRAMES[choice]


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown(
    f'<div style="color:{BLUE};font-size:1.1rem;font-weight:700;letter-spacing:0.08em;">✈ JET ENGINE COSTS</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Section",
    ["Overview", "Metals", "Energy", "FX & Macro", "Relationships"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

try:
    last = q("SELECT MAX(fetched_at) AS ts FROM price_snapshots")["ts"].iloc[0]
    st.sidebar.caption(f"Last fetch: {last[:19] if last else 'No data yet'}")
except Exception:
    st.sidebar.caption("No data yet")
st.sidebar.caption("Yahoo Finance · World Bank")


# ── Overview ──────────────────────────────────────────────────────────────────
if page == "Overview":

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#06091A 0%,#0C1629 60%,#00205B 100%);
                border:1px solid {BLUE_DARK};border-radius:10px;padding:24px 32px;margin-bottom:24px;">
        <div style="font-size:0.75rem;color:{BLUE_DIM};letter-spacing:0.15em;text-transform:uppercase;margin-bottom:4px;">
            Real-time market intelligence
        </div>
        <div style="font-size:2rem;font-weight:700;color:{BLUE};letter-spacing:0.04em;margin-bottom:6px;">
            ✈ Jet Engine Cost Dashboard
        </div>
        <div style="color:{BLUE_DIM};font-size:0.95rem;">
            Live commodity, energy and macroeconomic data relevant to jet engine manufacturing costs
        </div>
    </div>
    """, unsafe_allow_html=True)

    snap = q("""
        SELECT c.name, cat.name AS category, c.unit, ps.price, ps.fetched_at
        FROM price_snapshots ps
        JOIN commodities c  ON ps.commodity_id = c.id
        JOIN categories cat ON c.category_id   = cat.id
        WHERE ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
        ORDER BY cat.name, c.name
    """)

    metals = snap[snap["category"] == "metal"]
    energy = snap[snap["category"] == "energy"]
    fx     = snap[snap["category"] == "fx_rate"]

    n_total     = len(snap)
    n_hist      = q("SELECT COUNT(*) AS n FROM price_history")["n"].iloc[0]
    n_countries = q("SELECT COUNT(*) AS n FROM countries")["n"].iloc[0]
    n_macro     = q("SELECT COUNT(*) AS n FROM macro_data")["n"].iloc[0]

    s1, s2, s3, s4 = st.columns(4)

    def stat_card(col, label, value, sub=""):
        col.markdown(f"""
        <div style="background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:8px;
                    padding:14px 18px;text-align:center;">
            <div style="font-size:1.6rem;font-weight:700;color:{BLUE};">{value}</div>
            <div style="font-size:0.7rem;color:{BLUE_DIM};text-transform:uppercase;
                        letter-spacing:0.1em;margin-top:2px;">{label}</div>
            {f'<div style="font-size:0.65rem;color:{BLUE_DARK};margin-top:2px;">{sub}</div>' if sub else ''}
        </div>""", unsafe_allow_html=True)

    stat_card(s1, "Commodities tracked", n_total)
    stat_card(s2, "Weekly history rows", f"{n_hist:,}")
    stat_card(s3, "Countries monitored", n_countries)
    stat_card(s4, "Macro data points", n_macro)

    st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)

    def sparkline(commodity_names: list, height: int = 120) -> go.Figure:
        ph = q(f"""
            SELECT c.name, ph.date, ph.close
            FROM price_history ph JOIN commodities c ON ph.commodity_id = c.id
            WHERE c.name IN ({','.join('?'*len(commodity_names))})
              AND ph.date >= DATE('now', '-3 months')
            ORDER BY ph.date
        """, tuple(commodity_names))
        fig = go.Figure()
        for i, name in enumerate(commodity_names):
            d = ph[ph["name"] == name]
            fig.add_trace(go.Scatter(
                x=d["date"], y=d["close"], name=name, mode="lines",
                line=dict(color=TRACE_COLORS[i % len(TRACE_COLORS)], width=1.5),
                hovertemplate="%{x}<br>%{y:.2f}<extra>" + name + "</extra>",
            ))
        fig.update_layout(
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            height=height, margin=dict(l=0, r=0, t=0, b=0),
            xaxis=dict(visible=False), yaxis=dict(visible=False, showgrid=False),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLUE_DIM, size=10),
                        orientation="h", x=0, y=1.15),
            showlegend=True,
        )
        return fig

    def section_divider(icon: str, label: str):
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
            <div style="height:1px;flex:1;background:linear-gradient(90deg,{BLUE_DARK},transparent);"></div>
            <div style="color:{BLUE};font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;">{icon} {label}</div>
            <div style="height:1px;flex:1;background:linear-gradient(270deg,{BLUE_DARK},transparent);"></div>
        </div>""", unsafe_allow_html=True)

    section_divider("⬡", "Metals")
    mcols = st.columns([1,1,1,1,2])
    metal_names = metals["name"].tolist()
    for i, (_, row) in enumerate(metals.iterrows()):
        if i < 4:
            with mcols[i]:
                fmt = f"${row['price']:,.2f}" if row["price"] else "N/A"
                st.metric(row["name"], fmt, help=row["unit"])
    if len(metal_names) > 4:
        more = st.columns(len(metal_names) - 4)
        for i, (_, row) in enumerate(metals.iloc[4:].iterrows()):
            with more[i]:
                fmt = f"${row['price']:,.2f}" if row["price"] else "N/A"
                st.metric(row["name"], fmt, help=row["unit"])
    with mcols[4]:
        if metal_names:
            st.plotly_chart(sparkline(metal_names[:5]), use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    section_divider("⚡", "Energy")
    energy_names = energy["name"].tolist()
    ecols = st.columns([1,1,1,1,2])
    for i, (_, row) in enumerate(energy.iterrows()):
        if i < 4:
            with ecols[i]:
                fmt = f"${row['price']:,.2f}" if row["price"] else "N/A"
                st.metric(row["name"], fmt, help=row["unit"])
    if len(energy_names) > 4:
        more = st.columns(len(energy_names) - 4)
        for i, (_, row) in enumerate(energy.iloc[4:].iterrows()):
            with more[i]:
                fmt = f"${row['price']:,.2f}" if row["price"] else "N/A"
                st.metric(row["name"], fmt, help=row["unit"])
    with ecols[4]:
        if energy_names:
            st.plotly_chart(sparkline(energy_names[:4]), use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    section_divider("💱", "FX Rates (GBP)")
    fx_names = fx["name"].tolist()
    fxcols = st.columns([1,1,1,1,2])
    for i, (_, row) in enumerate(fx.iterrows()):
        if i < 4:
            with fxcols[i]:
                fmt = f"{row['price']:.4f}" if row["price"] else "N/A"
                st.metric(row["name"], fmt, help=row["unit"])
    if len(fx_names) > 4:
        more = st.columns(len(fx_names) - 4)
        for i, (_, row) in enumerate(fx.iloc[4:].iterrows()):
            with more[i]:
                fmt = f"{row['price']:.4f}" if row["price"] else "N/A"
                st.metric(row["name"], fmt, help=row["unit"])
    with fxcols[4]:
        if fx_names:
            st.plotly_chart(sparkline(fx_names[:4]), use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

    section_divider("🔩", "Engine Component Exposure")
    comp = q("""
        SELECT jec.name AS "Component", c.name AS "Material",
               ROUND(ps.price, 2) AS "Latest Price", c.unit AS "Unit"
        FROM component_materials cm
        JOIN jet_engine_components jec ON cm.component_id = jec.id
        JOIN commodities c             ON cm.commodity_id = c.id
        LEFT JOIN price_snapshots ps   ON ps.commodity_id = c.id
            AND ps.id = (SELECT MAX(id) FROM price_snapshots WHERE commodity_id = c.id)
        ORDER BY jec.name, c.name
    """)
    st.dataframe(
        comp,
        use_container_width=True,
        hide_index=True,
        column_config={"Latest Price": st.column_config.NumberColumn(format="$%.2f")},
    )


# ── Metals ────────────────────────────────────────────────────────────────────
elif page == "Metals":
    st.markdown("# Metals")

    metals_list = q(
        "SELECT name FROM commodities WHERE category_id=(SELECT id FROM categories WHERE name='metal') ORDER BY name"
    )["name"].tolist()
    selected = st.multiselect("Select metals to chart", metals_list, default=metals_list[:3])

    if selected:
        tf = timeframe_radio("metals_tf")

        ph = q(f"""
            SELECT c.name, ph.date, ph.year, ph.month, ph.week, ph.close
            FROM price_history ph
            JOIN commodities c ON ph.commodity_id = c.id
            WHERE c.name IN ({','.join('?'*len(selected))})
              AND ph.date >= DATE('now', '{tf}')
            ORDER BY ph.date
        """, tuple(selected))

        if ph.empty:
            st.info("No historical data yet — run run_all.py.")
        else:
            show_trend = st.checkbox("Show trend projection (6M / 1Y)", value=False, key="metals_trend")
            fig = go.Figure()
            for i, metal in enumerate(selected):
                d = ph[ph["name"] == metal]
                fig.add_trace(go.Scatter(
                    x=d["date"], y=d["close"],
                    name=metal, mode="lines",
                    line=dict(color=TRACE_COLORS[i % len(TRACE_COLORS)], width=1.5),
                ))
                if show_trend and len(selected) == 1:
                    add_trend_projection(fig, d, name=metal, color=GOLD)
            if show_trend and len(selected) > 1:
                st.caption("Trend projection is shown for single-metal selection.")
            dark_layout(fig, "Weekly Close Price (USD)")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Latest snapshots")
    snap = q("""
        SELECT c.name, ps.price, c.unit, ps.fetched_at
        FROM price_snapshots ps JOIN commodities c ON ps.commodity_id=c.id
        WHERE c.category_id=(SELECT id FROM categories WHERE name='metal')
        AND ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
    """)
    st.dataframe(snap, use_container_width=True, hide_index=True)


# ── Energy ────────────────────────────────────────────────────────────────────
elif page == "Energy":
    st.markdown("# Energy")

    energy_list = q(
        "SELECT name FROM commodities WHERE category_id=(SELECT id FROM categories WHERE name='energy') ORDER BY name"
    )["name"].tolist()
    selected = st.multiselect("Select energy commodities", energy_list, default=energy_list[:3])

    if selected:
        tf = timeframe_radio("energy_tf")

        ph = q(f"""
            SELECT c.name, ph.date, ph.open, ph.high, ph.low, ph.close
            FROM price_history ph
            JOIN commodities c ON ph.commodity_id = c.id
            WHERE c.name IN ({','.join('?'*len(selected))})
              AND ph.date >= DATE('now', '{tf}')
            ORDER BY ph.date
        """, tuple(selected))

        if ph.empty:
            st.info("No historical data yet — run run_all.py.")
        else:
            if len(selected) == 1:
                d = ph[ph["name"] == selected[0]]
                fig = go.Figure(go.Candlestick(
                    x=d["date"], open=d["open"], high=d["high"],
                    low=d["low"], close=d["close"], name=selected[0],
                    increasing_line_color=BLUE, decreasing_line_color="#F06A9F",
                ))
                show_trend = st.checkbox("Show trend projection (6M / 1Y)", value=False, key="energy_trend")
                if show_trend:
                    add_trend_projection(fig, d, name=selected[0], color=GOLD)
                dark_layout(fig, f"{selected[0]} — Weekly OHLC")
            else:
                fig = go.Figure()
                for i, name in enumerate(selected):
                    d = ph[ph["name"] == name]
                    fig.add_trace(go.Scatter(
                        x=d["date"], y=d["close"], name=name, mode="lines",
                        line=dict(color=TRACE_COLORS[i % len(TRACE_COLORS)], width=1.5),
                    ))
                dark_layout(fig, "Weekly Close Price (USD)")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Latest snapshots")
    snap = q("""
        SELECT c.name, ps.price, c.unit, ps.fetched_at
        FROM price_snapshots ps JOIN commodities c ON ps.commodity_id=c.id
        WHERE c.category_id=(SELECT id FROM categories WHERE name='energy')
        AND ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
    """)
    st.dataframe(snap, use_container_width=True, hide_index=True)


# ── FX & Macro ────────────────────────────────────────────────────────────────
elif page == "FX & Macro":
    st.markdown("# FX & Macroeconomic Indicators")

    tab_fx, tab_macro = st.tabs(["FX Rates", "Macro Indicators"])

    with tab_fx:
        fx_list = q(
            "SELECT name FROM commodities WHERE category_id=(SELECT id FROM categories WHERE name='fx_rate') ORDER BY name"
        )["name"].tolist()
        selected = st.multiselect("GBP pairs", fx_list, default=fx_list)

        if selected:
            tf = timeframe_radio("fx_tf")

            ph = q(f"""
                SELECT c.name, ph.date, ph.close
                FROM price_history ph JOIN commodities c ON ph.commodity_id=c.id
                WHERE c.name IN ({','.join('?'*len(selected))})
                  AND ph.date >= DATE('now', '{tf}')
                ORDER BY ph.date
            """, tuple(selected))

            if ph.empty:
                st.info("No FX history yet — run run_all.py.")
            else:
                show_trend = st.checkbox("Show trend projection (6M / 1Y)", value=False, key="fx_trend")
                fig = go.Figure()
                for i, pair in enumerate(selected):
                    d = ph[ph["name"] == pair]
                    fig.add_trace(go.Scatter(
                        x=d["date"], y=d["close"], name=pair, mode="lines",
                        line=dict(color=TRACE_COLORS[i % len(TRACE_COLORS)], width=1.5),
                    ))
                    if show_trend and len(selected) == 1:
                        add_trend_projection(fig, d, name=pair, color=GOLD)
                if show_trend and len(selected) > 1:
                    st.caption("Trend projection is shown for single-pair selection.")
                dark_layout(fig, "GBP FX Rates — Weekly Close")
                st.plotly_chart(fig, use_container_width=True)

    with tab_macro:
        countries  = q("SELECT name FROM countries ORDER BY name")["name"].tolist()
        indicators = q("SELECT name FROM macro_indicators ORDER BY name")["name"].tolist()
        col1, col2 = st.columns(2)
        sel_countries  = col1.multiselect("Countries",  countries,  default=["United Kingdom","United States","China"])
        sel_indicators = col2.multiselect("Indicators", indicators, default=["CPI Inflation","GDP Growth"])

        if sel_countries and sel_indicators:
            macro = q(f"""
                SELECT co.name AS country, mi.name AS indicator, md.year, md.value, mi.unit
                FROM macro_data md
                JOIN countries co        ON md.country_id   = co.id
                JOIN macro_indicators mi ON md.indicator_id = mi.id
                WHERE co.name IN ({','.join('?'*len(sel_countries))})
                  AND mi.name IN ({','.join('?'*len(sel_indicators))})
                ORDER BY mi.name, co.name, md.year
            """, tuple(sel_countries + sel_indicators))

            if macro.empty:
                st.info("No macro data yet — run run_all.py.")
            else:
                for ind in sel_indicators:
                    d = macro[macro["indicator"] == ind]
                    if d.empty:
                        continue
                    fig = go.Figure()
                    for i, country in enumerate(sel_countries):
                        cd = d[d["country"] == country].sort_values("year")
                        if cd.empty:
                            continue
                        fig.add_trace(go.Bar(
                            x=cd["year"].astype(str), y=cd["value"],
                            name=country, marker_color=TRACE_COLORS[i % len(TRACE_COLORS)],
                        ))
                    unit = d["unit"].iloc[0] if not d.empty else ""
                    dark_layout(fig, f"{ind}  [{unit}]")
                    fig.update_layout(barmode="group")
                    st.plotly_chart(fig, use_container_width=True)


# ── Relationships ─────────────────────────────────────────────────────────────
elif page == "Relationships":
    st.markdown("# Price Relationships")
    st.caption("Known economic linkages between commodities and macro indicators seeded into the database.")

    st.markdown("### Commodity → Commodity")
    comm_rel = q("""
        SELECT c1.name AS from_commodity, rt.name AS relationship,
               c2.name AS to_commodity,  cr.strength, cr.notes
        FROM commodity_relationships cr
        JOIN commodities c1       ON cr.from_commodity_id    = c1.id
        JOIN commodities c2       ON cr.to_commodity_id      = c2.id
        JOIN relationship_types rt ON cr.relationship_type_id = rt.id
        ORDER BY rt.name, cr.strength DESC
    """)
    st.dataframe(comm_rel, use_container_width=True, hide_index=True)

    st.markdown("### Macro Indicator → Commodity")
    macro_rel = q("""
        SELECT mi.name AS indicator, c.name AS commodity,
               rt.name AS relationship, mcr.direction, mcr.strength, mcr.notes
        FROM macro_commodity_relationships mcr
        JOIN macro_indicators mi   ON mcr.indicator_id        = mi.id
        JOIN commodities c         ON mcr.commodity_id        = c.id
        JOIN relationship_types rt ON mcr.relationship_type_id = rt.id
        ORDER BY mi.name, mcr.strength DESC
    """)
    st.dataframe(macro_rel, use_container_width=True, hide_index=True)

    st.markdown("### Engine Components at Risk")
    comp_risk = q("""
        SELECT jec.name AS component, c.name AS material,
               ps.price, c.unit
        FROM component_materials cm
        JOIN jet_engine_components jec ON cm.component_id = jec.id
        JOIN commodities c             ON cm.commodity_id = c.id
        LEFT JOIN price_snapshots ps   ON ps.commodity_id = c.id
            AND ps.id = (SELECT MAX(id) FROM price_snapshots WHERE commodity_id = c.id)
        ORDER BY jec.name, c.name
    """)
    st.dataframe(comp_risk, use_container_width=True, hide_index=True)
