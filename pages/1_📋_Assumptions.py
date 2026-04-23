"""
Assumptions Register — external (market-linked) and internal deliverability assumptions.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

_ROOT = str(Path(__file__).parent.parent)
for _p in [_ROOT, str(Path(__file__).parent.parent / "Database"),
           str(Path(__file__).parent.parent / "LLM")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.shared import (
    BLUE, BLUE_DIM, BLUE_DARK, GOLD, BG, CARD_BG, GREEN, AMBER, RED,
    jic_label as _jic, db_query as _qmain, get_gbp_usd,
    badge as _badge, RISK_BADGE_COLORS as _RISK_BADGE_COLORS,
    CLASS_BADGE_COLORS as _CLASS_BADGE_COLORS, inject_theme,
)

from assumptions_tracker_db import (
    init_tracker_tables, load_tracker, add_tracker_row, update_tracker_row,
    delete_tracker_row, delete_all_tracker_rows, get_audit_log, seed_if_empty,
)
from ai_assessor import (
    ensure_ai_columns,
    load_unassessed, load_all_rows, assess_rows, get_price_drift_map,
    load_unassessed_tracker, load_all_tracker_rows,
    assess_tracker_rows, assess_single_tracker_row,
)
from ollama_client import is_ollama_running, list_models

import sqlite3
MAIN_DB = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"

st.set_page_config(page_title="Assumptions Register", page_icon="📋", layout="wide")
inject_theme(".risk-high{color:#EF5350;font-weight:700;}.risk-med{color:#FFA726;font-weight:700;}.risk-low{color:#66BB6A;font-weight:700;}")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _drift_color(pct: float) -> str:
    if abs(pct) < 5:   return BLUE_DIM
    if pct > 15 or pct < -10: return RED
    if pct > 5  or pct < -3:  return AMBER
    return GREEN


ASSUMPTION_ID_RE = re.compile(r"^AS\d{3}$")
CATEGORIES_INTERNAL = ["Economic / Inflation", "Commercial", "Material", "Third-party"]
STATUS_OPTIONS = ["Open", "Monitor", "Mitigated", "Closed"]

# ── Init on startup ────────────────────────────────────────────────────────────
init_tracker_tables()
ensure_ai_columns()

if "tracker_df" not in st.session_state:
    st.session_state.tracker_df = pd.DataFrame(load_tracker())


# ══════════════════════════════════════════════════════════════════════════════
# EXTERNAL ASSUMPTIONS — helper functions
# ══════════════════════════════════════════════════════════════════════════════

def _load_external_with_live_prices() -> pd.DataFrame:
    """Load Matt's assumptions joined to live market prices for drift comparison."""
    assumptions = _qmain("SELECT * FROM assumptions ORDER BY project_id, assumption_id")
    if assumptions.empty:
        return assumptions

    # Latest price per commodity ticker from price_snapshots
    live = _qmain("""
        SELECT c.ticker, ps.price AS live_usd, ps.fetched_at
        FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id = c.id
        WHERE ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
          AND c.ticker IS NOT NULL AND c.ticker != ''
    """)

    # GBP/USD rate
    fx = _qmain("""
        SELECT ps.price FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id = c.id
        WHERE c.name IN ('GBP/USD', 'GBPUSD=X')
        ORDER BY ps.id DESC LIMIT 1
    """)
    gbp_rate = float(fx["price"].iloc[0]) if not fx.empty else 1.27

    if not live.empty:
        # Assumptions use short tickers (ALI), commodities use Yahoo format (ALI=F).
        # Add a normalised column to match both forms.
        live["ticker_short"] = live["ticker"].str.replace(r"=F$", "", regex=True)
        assumptions["ticker_short"] = assumptions["ticker"]
        assumptions = assumptions.merge(
            live[["ticker_short", "live_usd", "fetched_at"]],
            on="ticker_short", how="left",
        ).drop(columns=["ticker_short"])
    else:
        assumptions["live_usd"] = None
        assumptions["fetched_at"] = None

    # Convert assumed price to USD for comparison
    def _assumed_usd(row):
        p = row.get("price_per_unit")
        if p is None or pd.isna(p):
            return None
        cur = str(row.get("currency", "USD")).upper()
        if cur == "GBP":
            return float(p) * gbp_rate
        return float(p)

    assumptions["assumed_usd"] = assumptions.apply(_assumed_usd, axis=1)
    assumptions["gbp_rate"] = gbp_rate

    def _drift(row):
        a = row.get("assumed_usd")
        l = row.get("live_usd")
        if a is None or l is None or pd.isna(a) or pd.isna(l) or float(a) == 0:
            return None
        raw = (float(l) - float(a)) / float(a) * 100.0
        return max(-150.0, min(150.0, raw))  # cap outliers from data anomalies

    assumptions["price_drift_pct"] = assumptions.apply(_drift, axis=1)
    return assumptions


_MARKET_TYPES = {"material", "energy"}  # assumption types that have live market prices


def _market_price_table(rows_df: pd.DataFrame, section_label: str) -> None:
    """Render an HTML price-drift table for market-linked assumptions."""
    rows_html = []
    for _, r in rows_df.iterrows():
        drift = r.get("price_drift_pct")
        drift_str  = f"{drift:+.1f}%" if drift is not None and not pd.isna(drift) else "—"
        drift_color = _drift_color(drift) if drift is not None and not pd.isna(drift) else BLUE_DIM
        live_usd   = r.get("live_usd")
        live_str   = f"${live_usd:,.3f}" if live_usd is not None and not pd.isna(live_usd) else "—"
        assumed    = r.get("price_per_unit")
        assumed_str = (
            f"{r.get('currency','USD')} {float(assumed):,.3f}/{r.get('unit','')}"
            if assumed is not None and not pd.isna(assumed) else "—"
        )
        total = r.get("total_cost")
        total_str = f"${total:,.0f}" if total is not None and not pd.isna(total) else "—"
        ai_cls  = r.get("ai_classification") or ""
        ai_risk = r.get("ai_risk_level") or ""
        ai_rat  = r.get("ai_rationale") or "Not assessed"
        cls_c,  cls_bg  = _CLASS_BADGE_COLORS.get(ai_cls,  (BLUE_DIM, BLUE_DARK))
        risk_c, risk_bg = _RISK_BADGE_COLORS.get(ai_risk, (BLUE_DIM, BLUE_DARK))
        ai_html = (
            f"{_badge(ai_cls, cls_c, cls_bg)} {_badge(ai_risk, risk_c, risk_bg)}"
            if ai_cls else f"<span style='color:{BLUE_DIM};font-size:0.7rem;'>—</span>"
        )
        rows_html.append(
            f"<tr>"
            f"<td style='padding:5px 10px;color:#D0E8FF;' title='{ai_rat}'>{r.get('assumption','')}</td>"
            f"<td style='padding:5px 10px;color:{BLUE_DIM};'>{r.get('ticker','')}</td>"
            f"<td style='padding:5px 10px;color:#D0E8FF;'>{assumed_str}</td>"
            f"<td style='padding:5px 10px;color:#D0E8FF;'>{live_str}</td>"
            f"<td style='padding:5px 10px;color:{drift_color};font-weight:700;'>{drift_str}</td>"
            f"<td style='padding:5px 10px;color:#D0E8FF;'>{total_str}</td>"
            f"<td style='padding:5px 10px;'>{ai_html}</td>"
            f"</tr>"
        )
    if rows_html:
        st.markdown(f"**{section_label}**")
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;'>"
            f"<thead><tr style='background:{BLUE_DARK};'>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>Assumption</th>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>Ticker</th>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>Assumed Price</th>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>Live Market</th>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>Drift</th>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>Total Cost</th>"
            f"<th style='padding:6px 10px;color:{BLUE};text-align:left;'>AI Assessment</th>"
            f"</tr></thead><tbody>{''.join(rows_html)}</tbody></table>",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)


def _render_external(df: pd.DataFrame) -> None:
    """Render the external (market-driven) assumptions register — metals, energy, FX."""
    st.markdown("### 🌍 External Assumptions — Market-Driven Costs")
    st.caption(
        "**External** assumptions are driven by live market prices — commodity metals, energy (oil & gas), "
        "and FX rates. These are outside the team's control and are tracked against the prices assumed "
        "at project inception. Drift = (live price − assumed price) / assumed price."
    )

    if df.empty:
        st.info("No external assumptions found in the database.")
        return

    # ── Summary metrics ────────────────────────────────────────────────────────
    market_rows = df[df["assumption_type"].isin(_MARKET_TYPES)].dropna(subset=["price_drift_pct"])
    energy_rows = df[df["assumption_type"] == "energy"].dropna(subset=["price_drift_pct"])
    n_high_drift = int((market_rows["price_drift_pct"].abs() > 15).sum()) if not market_rows.empty else 0
    avg_drift    = float(market_rows["price_drift_pct"].mean()) if not market_rows.empty else 0.0
    avg_energy_drift = float(energy_rows["price_drift_pct"].mean()) if not energy_rows.empty else 0.0
    n_projects   = df["project_id"].nunique()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total assumptions", len(df))
    c2.metric("Projects", n_projects)
    c3.metric("High drift items (>±15%)", n_high_drift,
              delta="Review needed" if n_high_drift > 0 else None, delta_color="inverse")
    c4.metric("Avg metals drift", f"{avg_drift:+.1f}%")
    c5.metric("Avg energy drift", f"{avg_energy_drift:+.1f}%",
              help="Brent Crude & Natural Gas vs assumed prices")

    # ── Filter by project ──────────────────────────────────────────────────────
    all_projects = sorted(df["project_name"].dropna().unique().tolist())
    selected_projects = st.multiselect(
        "Filter by project", all_projects, default=all_projects, key="ext_proj_filter"
    )
    view = df[df["project_name"].isin(selected_projects)] if selected_projects else df

    # ── Per-project expanders ──────────────────────────────────────────────────
    for proj_name, proj_df in view.groupby("project_name"):
        market_df = proj_df[proj_df["assumption_type"].isin(_MARKET_TYPES)]
        other_df  = proj_df[~proj_df["assumption_type"].isin(_MARKET_TYPES)]

        total_market_cost = market_df["total_cost"].sum() if not market_df.empty else 0
        with st.expander(
            f"📁 {proj_name}  —  {len(proj_df)} assumptions  |  "
            f"Market cost: ${total_market_cost:,.0f}",
            expanded=True,
        ):
            mat_df = proj_df[proj_df["assumption_type"] == "material"].copy()
            nrg_df = proj_df[proj_df["assumption_type"] == "energy"].copy()

            _market_price_table(mat_df, "Metals — assumed vs live market price")
            _market_price_table(nrg_df, "Energy — assumed vs live market price")

            if not other_df.empty:
                st.markdown("**Other assumptions (non-market)**")
                other_display = other_df[
                    ["assumption_id", "category", "assumption_type", "location",
                     "assumption", "event_date", "price_per_unit", "currency", "unit"]
                ].copy()
                st.dataframe(other_display, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL TRACKER — App_2 logic adapted
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AdjResult:
    adjusted_value: float
    net_drift_pct: float
    dependency_factor_pct: float


def _parse_deps(text: str) -> List[str]:
    return [x.strip() for x in text.split(",") if x.strip()] if text else []


def _dep_factor(row: pd.Series, by_id: Dict) -> float:
    deps = _parse_deps(str(row.get("dependencies", "")))
    if not deps:
        return 0.0
    total_w = weighted = 0.0
    for d in deps:
        dep = by_id.get(d)
        if dep is None:
            continue
        net = float(dep["internal_drift_pct"]) + float(dep["external_drift_pct"])
        conf = float(dep["confidence_score"]) / 100.0
        weighted += net * conf
        total_w += conf
    return (weighted / total_w) if total_w else 0.0


def _adjust(row: pd.Series, by_id: Dict) -> AdjResult:
    baseline = float(row["baseline_value"])
    net = float(row["internal_drift_pct"]) + float(row["external_drift_pct"])
    conf = float(row["confidence_score"]) / 100.0
    dep = _dep_factor(row, by_id)
    return AdjResult(
        adjusted_value=baseline * (1 + (net * conf) + (dep * 0.5)),
        net_drift_pct=net,
        dependency_factor_pct=dep,
    )


def _review_status(last_review: date, interval: int) -> str:
    age = (date.today() - last_review).days
    if age > interval:
        return "Overdue"
    if age >= interval * 0.8:
        return "Due soon"
    return "Current"


def _prepare_tracker_view(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    by_id = {r["assumption_id"]: r for _, r in df.iterrows()}
    rows = []
    for _, row in df.iterrows():
        res = _adjust(row, by_id)
        last = row["last_review_date"]
        if isinstance(last, str):
            last = datetime.strptime(last, "%Y-%m-%d").date()
        rows.append({
            **row.to_dict(),
            "net_drift_pct": res.net_drift_pct,
            "dependency_factor_pct": res.dependency_factor_pct,
            "adjusted_value": res.adjusted_value,
            "drift_type": "Internal-driven" if abs(float(row["internal_drift_pct"])) >= abs(float(row["external_drift_pct"])) else "External-driven",
            "confidence_band": "High" if float(row["confidence_score"]) >= 80 else ("Medium" if float(row["confidence_score"]) >= 60 else "Low"),
            "review_age_days": (date.today() - last).days,
            "review_status": _review_status(last, int(row["review_interval_days"])),
        })
    out = pd.DataFrame(rows)
    return out.sort_values(["review_status", "category", "assumption_id"])


def _next_asid(used: set) -> str:
    i = 1
    while True:
        c = f"AS{i:03d}"
        if c not in used:
            return c
        i += 1


# ── Internal tracker card ──────────────────────────────────────────────────────
def _tracker_card(row: dict) -> None:
    conf      = int(row.get("confidence_score") or 50)
    jic_label, jic_color = _jic(conf)  # _jic imported as alias for jic_label from shared
    net_drift = (float(row.get("internal_drift_pct") or 0)
                 + float(row.get("external_drift_pct") or 0)) * 100
    drift_color = "#EF5350" if abs(net_drift) > 15 else "#FFA726" if abs(net_drift) > 5 else BLUE_DIM
    rev_status  = row.get("review_status", "Current")
    rev_color   = {"Overdue": "#EF5350", "Due soon": "#FFA726", "Current": "#66BB6A"}.get(rev_status, BLUE_DIM)
    status_txt  = row.get("status", "Open")
    ai_cls      = row.get("ai_classification") or ""
    ai_risk     = row.get("ai_risk_level") or ""
    ai_rat      = row.get("ai_rationale") or ""
    cls_c, cls_bg   = _CLASS_BADGE_COLORS.get(ai_cls,  (BLUE_DIM, BLUE_DARK))
    risk_c, risk_bg = _RISK_BADGE_COLORS.get(ai_risk,  (BLUE_DIM, BLUE_DARK))
    ai_html = (
        f"{_badge(ai_cls, cls_c, cls_bg)} {_badge(ai_risk, risk_c, risk_bg)}"
        if ai_cls else f"<span style='color:{BLUE_DIM};font-size:0.7rem;'>No AI assessment yet</span>"
    )
    st.markdown(f"""
    <div style='background:{CARD_BG};border-left:3px solid {jic_color};border-radius:8px;
                padding:12px 16px;margin-bottom:8px;'>
      <div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;'>
        <div style='flex:3;min-width:200px;'>
          <div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;'>
            <span style='background:{BLUE_DARK};color:{BLUE};font-size:0.68rem;font-weight:700;
                         padding:2px 8px;border-radius:4px;'>{row.get("assumption_id","")}</span>
            <span style='color:#FFFFFF;font-weight:600;font-size:0.95rem;'>{row.get("title","")}</span>
          </div>
          <div style='color:{BLUE_DIM};font-size:0.75rem;margin-bottom:4px;'>
            {str(row.get("description",""))[:100]}{"…" if len(str(row.get("description",""))) > 100 else ""}
          </div>
          <div style='color:{BLUE_DIM};font-size:0.68rem;'>
            <span style='color:{GOLD};'>{row.get("project_name","")}</span>
            &nbsp;·&nbsp; Owner: <span style='color:#D0E8FF;'>{row.get("owner","")}</span>
            &nbsp;·&nbsp; Category: <span style='color:#D0E8FF;'>{row.get("category","")}</span>
            &nbsp;·&nbsp; Status: <span style='color:#D0E8FF;'>{status_txt}</span>
          </div>
        </div>
        <div style='display:flex;gap:20px;flex-wrap:wrap;align-items:center;'>
          <div style='text-align:center;'>
            <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;letter-spacing:0.08em;'>Confidence</div>
            <div style='font-size:1.1rem;font-weight:700;color:{jic_color};'>{conf}/100</div>
            <div style='font-size:0.62rem;color:{jic_color};font-style:italic;'>{jic_label}</div>
          </div>
          <div style='text-align:center;'>
            <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;letter-spacing:0.08em;'>Net drift</div>
            <div style='font-size:1.1rem;font-weight:700;color:{drift_color};'>{net_drift:+.1f}%</div>
            <div style='font-size:0.62rem;color:{BLUE_DIM};'>int+ext</div>
          </div>
          <div style='text-align:center;'>
            <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;letter-spacing:0.08em;'>Review</div>
            <div style='font-size:0.85rem;font-weight:700;color:{rev_color};'>{rev_status}</div>
            <div style='font-size:0.62rem;color:{BLUE_DIM};'>{row.get("review_age_days",0)}d ago</div>
          </div>
          <div>{ai_html}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ── Review Gantt chart ────────────────────────────────────────────────────────
def _review_timeline(df_view: pd.DataFrame) -> None:
    tl = df_view.copy()
    tl["window_start"] = pd.to_datetime(tl["last_review_date"])
    tl["window_end"]   = tl["window_start"] + pd.to_timedelta(tl["review_interval_days"].astype(int), unit="D")
    tl["today"]        = pd.Timestamp(date.today())
    tl["label"]        = tl.apply(lambda r: f"{r['assumption_id']} · {str(r['title'])[:40]}", axis=1)
    tl = tl.sort_values(["window_end", "assumption_id"])

    chart = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": tl.to_dict(orient="records")},
        "background": "#06091A",
        "height": min(600, max(160, 26 * len(tl))),
        "layer": [
            {
                "mark": {"type": "bar", "cornerRadius": 3, "height": 14},
                "encoding": {
                    "y": {"field": "label", "type": "ordinal", "sort": None,
                          "axis": {"labelColor": "#4FC3F7", "titleColor": "#1A8CBF"}},
                    "x": {"field": "window_start", "type": "temporal",
                          "axis": {"labelColor": "#4FC3F7", "titleColor": "#1A8CBF", "gridColor": "#0C1629"}},
                    "x2": {"field": "window_end"},
                    "color": {
                        "field": "review_status", "type": "nominal",
                        "scale": {"domain": ["Current","Due soon","Overdue"],
                                  "range":  ["#2E7D32","#F9A825","#C62828"]},
                        "legend": {"labelColor": "#4FC3F7", "titleColor": "#1A8CBF"},
                    },
                    "tooltip": [
                        {"field": "assumption_id", "title": "ID"},
                        {"field": "title",         "title": "Title"},
                        {"field": "review_status", "title": "Review status"},
                        {"field": "window_end", "type": "temporal", "title": "Next due"},
                    ],
                },
            },
            {
                "mark": {"type": "rule", "strokeDash": [6, 4], "color": "#4FC3F7", "size": 2},
                "encoding": {"x": {"field": "today", "type": "temporal"}},
            },
        ],
    }
    st.vega_lite_chart(tl, chart, use_container_width=True)
    st.caption("Blue line = today. Bar spans last review date → next due date. Colour = review urgency.")


# ── Audit log renderer ────────────────────────────────────────────────────────
def _render_audit(assumption_id: Optional[str] = None) -> None:
    data = get_audit_log(assumption_id)
    if not data:
        st.info("No audit records.")
        return
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
    df = df.sort_values("timestamp", ascending=False)
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={
                     "timestamp": st.column_config.DatetimeColumn("Timestamp", format="YYYY-MM-DD HH:mm"),
                 })
    st.download_button("📥 Export audit log (CSV)", df.to_csv(index=False).encode(),
                       "audit_log.csv", "text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("# 📋 Assumptions Register")
st.caption(
    "**External** assumptions track market-driven costs (metals, energy, FX) against live prices. "
    "**Internal** assumptions track deliverability risks managed by the project team."
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    tracker_df_raw = st.session_state.tracker_df.copy()
    if not tracker_df_raw.empty:
        proj_opts     = sorted(tracker_df_raw["project_name"].dropna().unique().tolist()) if "project_name" in tracker_df_raw.columns else []
        proj_filter   = st.multiselect("Project", proj_opts, default=proj_opts)
        cat_opts      = sorted(tracker_df_raw["category"].unique().tolist())
        cat_filter    = st.multiselect("Category", cat_opts, default=cat_opts)
        status_filter = st.multiselect(
            "Status", sorted(tracker_df_raw["status"].unique().tolist()),
            default=sorted(tracker_df_raw["status"].unique().tolist()),
        )
        min_conf = st.slider("Min confidence", 0, 100, 0)
    else:
        proj_filter, cat_filter, status_filter, min_conf = [], [], [], 0
    st.divider()
    if st.button("🔄 Refresh", use_container_width=True):
        st.session_state.tracker_df = pd.DataFrame(load_tracker())
        st.rerun()
    with st.expander("Danger zone"):
        confirm = st.text_input("Type DELETE ALL to confirm")
        if st.button("Delete all internal assumptions", type="primary"):
            if confirm.strip().upper() == "DELETE ALL":
                delete_all_tracker_rows()
                st.session_state.tracker_df = pd.DataFrame(load_tracker())
                st.rerun()
            else:
                st.error("Type DELETE ALL to confirm.")

# ── 3 tabs ─────────────────────────────────────────────────────────────────────
tab_ext, tab_int, tab_ai = st.tabs([
    "🌍 External — Market Costs",
    "🏢 Internal — Deliverability Tracker",
    "🤖 AI Assessment",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — EXTERNAL
# ══════════════════════════════════════════════════════════════════════════════
with tab_ext:
    ext_df = _load_external_with_live_prices()
    _render_external(ext_df)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — INTERNAL TRACKER
# ══════════════════════════════════════════════════════════════════════════════
with tab_int:
    st.markdown("### 🏢 Internal Deliverability Tracker")
    st.caption(
        "Internal assumptions represent team-managed deliverability risks: supplier commitments, "
        "resource availability, quality gates, schedule milestones. Each has a confidence score "
        "reviewed periodically by the owner."
    )

    # Apply sidebar filters
    df_int = st.session_state.tracker_df.copy()
    if "project_name" in df_int.columns and proj_filter:
        df_int = df_int[df_int["project_name"].isin(proj_filter)]
    if cat_filter:
        df_int = df_int[df_int["category"].isin(cat_filter)]
    if status_filter:
        df_int = df_int[df_int["status"].isin(status_filter)]
    if not df_int.empty and min_conf > 0:
        df_int = df_int[df_int["confidence_score"] >= min_conf]
    df_view = _prepare_tracker_view(df_int)

    if df_view.empty:
        st.info("No internal assumptions tracked yet. Add one below.")
    else:
        # ── Summary metrics ────────────────────────────────────────────────────
        overdue  = int((df_view["review_status"] == "Overdue").sum())
        due_soon = int((df_view["review_status"] == "Due soon").sum())
        avg_conf = float(df_view["confidence_score"].mean())
        jic_lbl, jic_col = _jic(int(round(avg_conf)))
        high_risk = int((df_view.get("ai_risk_level", pd.Series(dtype=str)) == "High").sum()) if "ai_risk_level" in df_view.columns else 0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Tracked", len(df_view))
        m2.metric("Overdue reviews", overdue,
                  delta="Action needed" if overdue else None, delta_color="inverse")
        m3.metric("Due soon", due_soon)
        m4.metric("Avg confidence", f"{avg_conf:.0f}/100",
                  delta=jic_lbl, delta_color="normal")
        m5.metric("AI-flagged High risk", high_risk,
                  delta="Review" if high_risk else None, delta_color="inverse")

        # ── Confidence bar chart + history ────────────────────────────────────
        chart_col, hist_col = st.columns([3, 2])

        with chart_col:
            st.markdown("**Confidence by assumption**")
            conf_chart_df = df_view[["assumption_id", "title", "confidence_score", "confidence_band"]].copy()
            conf_chart_df["label"] = conf_chart_df.apply(
                lambda r: f"{r['assumption_id']} · {str(r['title'])[:35]}", axis=1
            )
            conf_chart_df = conf_chart_df.sort_values("confidence_score")
            conf_vl = {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "background": "#06091A",
                "data": {"values": conf_chart_df.to_dict(orient="records")},
                "height": min(500, max(120, 22 * len(conf_chart_df))),
                "mark": {"type": "bar", "cornerRadius": 3},
                "encoding": {
                    "y": {"field": "label", "type": "ordinal", "sort": None,
                          "axis": {"labelColor": "#4FC3F7", "labelFontSize": 10, "title": None}},
                    "x": {"field": "confidence_score", "type": "quantitative",
                          "scale": {"domain": [0, 100]},
                          "axis": {"labelColor": "#4FC3F7", "gridColor": "#0C1629", "title": "Confidence"}},
                    "color": {
                        "field": "confidence_band", "type": "nominal",
                        "scale": {"domain": ["High","Medium","Low"],
                                  "range":  ["#66BB6A","#FFA726","#EF5350"]},
                        "legend": {"labelColor": "#4FC3F7", "title": None},
                    },
                    "tooltip": [
                        {"field": "assumption_id", "title": "ID"},
                        {"field": "title", "title": "Title"},
                        {"field": "confidence_score", "title": "Confidence"},
                    ],
                },
            }
            st.vega_lite_chart(conf_chart_df, conf_vl, use_container_width=True)

        with hist_col:
            st.markdown("**Confidence over time (audit log)**")
            import sqlite3 as _sqlite3
            _con = _sqlite3.connect(MAIN_DB)
            hist_data = pd.read_sql_query("""
                SELECT assumption_id, CAST(new_value AS REAL) AS confidence,
                       timestamp
                FROM assumption_audit_log
                WHERE field_name='confidence_score'
                ORDER BY timestamp
            """, _con)
            _con.close()
            if hist_data.empty:
                st.info("No historical confidence data yet.")
            else:
                hist_data["confidence"] = pd.to_numeric(hist_data["confidence"], errors="coerce")
                hist_data["timestamp"]  = pd.to_datetime(hist_data["timestamp"], format="ISO8601")
                pivot = (
                    hist_data.pivot_table(index="timestamp", columns="assumption_id",
                                         values="confidence", aggfunc="mean")
                    .sort_index()
                    .ffill()
                )
                st.line_chart(pivot, height=300, use_container_width=True)
                st.caption("Each line = one tracked assumption. Shows confidence change over time.")

        st.divider()

        # ── Assumption cards ───────────────────────────────────────────────────
        for _, row in df_view.iterrows():
            _tracker_card(row.to_dict())

        # ── Review timeline ────────────────────────────────────────────────────
        with st.expander("📅 Review timeline", expanded=False):
            _review_timeline(df_view)

        # ── Audit log ─────────────────────────────────────────────────────────
        with st.expander("📜 Audit log", expanded=False):
            tracker_ids = df_view["assumption_id"].tolist()
            filter_id = st.selectbox(
                "Filter by assumption", [""] + tracker_ids,
                format_func=lambda x: "All" if x == "" else x,
                key="audit_filter",
            )
            _render_audit(filter_id if filter_id else None)

    st.divider()

    # ── Add new assumption ─────────────────────────────────────────────────────
    with st.expander("➕ Add new internal assumption", expanded=False):
        _project_names = ["Engine Casing", "Fan blade manufacturing", "Compressor assembly",
                          "Chamber fabrication", "Turbine manufacturing", "Nozzle assembly",
                          "Bearing assembly", "Fuel system components"]
        existing_ids = set(st.session_state.tracker_df["assumption_id"].tolist()) if not st.session_state.tracker_df.empty else set()
        with st.form("add_internal"):
            c1, c2, c3 = st.columns(3)
            aid        = c1.text_input("Assumption ID (ASXXX)", value=_next_asid(existing_ids))
            title      = c2.text_input("Title")
            category   = c3.selectbox("Category", CATEGORIES_INTERNAL)
            p1, p2 = st.columns(2)
            project_name = p1.selectbox("Project", _project_names)
            owner        = p2.text_input("Owner")
            description = st.text_area("Description / notes")
            c4, c5, c6 = st.columns(3)
            baseline   = c4.number_input("Baseline value", value=0.0, step=0.01)
            current    = c5.number_input("Current value",  value=0.0, step=0.01)
            unit       = c6.text_input("Unit")
            c7, c8, c9 = st.columns(3)
            int_drift  = c7.number_input("Internal drift %",  value=0.0, step=0.1)
            ext_drift  = c8.number_input("External drift %",  value=0.0, step=0.1)
            confidence = c9.slider("Confidence", 0, 100, 70)
            c10, c11, c12 = st.columns(3)
            last_review = c10.date_input("Last review date", value=date.today())
            interval    = c11.number_input("Review interval (days)", min_value=1, value=30)
            status      = c12.selectbox("Status", STATUS_OPTIONS)
            dependencies = st.text_input("Dependencies (comma-separated ASXXX)")
            reason       = st.text_input("Reason / notes (audit log)")

            if st.form_submit_button("Add to register"):
                norm_id = aid.strip().upper()
                if not norm_id or not title.strip() or not owner.strip():
                    st.error("ID, Title, and Owner are required.")
                elif not ASSUMPTION_ID_RE.match(norm_id):
                    st.error("ID must be ASXXX format.")
                elif norm_id in existing_ids:
                    st.error("That ID already exists.")
                else:
                    new_row = {
                        "assumption_id": norm_id, "project_name": project_name,
                        "title": title.strip(),
                        "category": category, "owner": owner.strip(),
                        "description": description.strip(),
                        "baseline_value": baseline, "current_value": current,
                        "unit": unit.strip(),
                        "internal_drift_pct": int_drift / 100.0,
                        "external_drift_pct": ext_drift / 100.0,
                        "confidence_score": int(confidence),
                        "last_review_date": last_review,
                        "review_interval_days": int(interval),
                        "dependencies": dependencies.strip(),
                        "status": status,
                    }
                    add_tracker_row(new_row, user="user", change_reason=reason.strip() or "Manual add")
                    st.session_state.tracker_df = pd.DataFrame(load_tracker())

                    # Auto-assess with AI if Ollama is running
                    _ollama_ok = is_ollama_running()
                    if _ollama_ok:
                        _models = list_models()
                        if _models:
                            with st.spinner(f"AI assessing {norm_id}…"):
                                try:
                                    res = assess_single_tracker_row(_models[0], {**new_row, "assumption_id": norm_id})
                                    cls_c, cls_bg   = _CLASS_BADGE_COLORS.get(res["classification"], (BLUE_DIM, BLUE_DARK))
                                    risk_c, risk_bg = _RISK_BADGE_COLORS.get(res["risk_level"],       (BLUE_DIM, BLUE_DARK))
                                    st.markdown(
                                        f"Added and assessed — "
                                        f"{_badge(res['classification'], cls_c, cls_bg)} "
                                        f"{_badge(res['risk_level'], risk_c, risk_bg)} "
                                        f"<span style='color:{BLUE_DIM};font-size:0.8rem;'>{res['rationale']}</span>",
                                        unsafe_allow_html=True,
                                    )
                                except Exception:
                                    st.success(f"Added {norm_id}. AI assessment failed — run it from the AI tab.")
                        else:
                            st.success(f"Added {norm_id}.")
                    else:
                        st.success(f"Added {norm_id}. Start Ollama to enable auto-assessment.")
                    st.rerun()

    # ── Update existing ────────────────────────────────────────────────────────
    if not st.session_state.tracker_df.empty:
        with st.expander("✏️ Update existing assumption", expanded=False):
            df_upd = st.session_state.tracker_df.copy()
            ids = df_upd["assumption_id"].tolist()
            sel = st.selectbox(
                "Select assumption",
                ids,
                format_func=lambda x: f"{x} — {df_upd[df_upd['assumption_id']==x]['title'].iloc[0]}",
                key="upd_sel",
            )
            row = df_upd[df_upd["assumption_id"] == sel].iloc[0]
            st.caption(f"Category: {row['category']}  |  Owner: {row['owner']}")
            with st.form("quick_update"):
                uc1, uc2 = st.columns(2)
                new_conf   = uc1.slider("Confidence", 0, 100, int(row["confidence_score"]))
                new_status = uc2.selectbox("Status", STATUS_OPTIONS,
                                           index=STATUS_OPTIONS.index(row["status"]))
                ud1, ud2, ud3 = st.columns(3)
                new_int_drift = ud1.number_input("Internal drift %", value=float(row["internal_drift_pct"]) * 100, step=0.1)
                new_ext_drift = ud2.number_input("External drift %", value=float(row["external_drift_pct"]) * 100, step=0.1)
                new_review    = ud3.date_input("Last review date", value=row["last_review_date"])
                reason        = st.text_input("Update reason")
                if st.form_submit_button("Apply update"):
                    update_tracker_row(sel, {
                        "confidence_score":   int(new_conf),
                        "last_review_date":   new_review,
                        "status":             new_status,
                        "internal_drift_pct": new_int_drift / 100.0,
                        "external_drift_pct": new_ext_drift / 100.0,
                    }, user="user", change_reason=reason.strip() or "Routine review")
                    st.session_state.tracker_df = pd.DataFrame(load_tracker())
                    st.success("Updated.")
                    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — AI ASSESSMENT
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown("### 🤖 AI Risk Assessment")
    st.caption(
        "Ollama classifies each assumption as **Risk**, **Assumption**, or **Assumption+Risk**, "
        "assigns a risk level (High / Medium / Low / N/A), and writes a one-sentence rationale. "
        "Results are saved to the database and shown on cards in the Internal tab."
    )

    _ollama_ok = is_ollama_running()
    if not _ollama_ok:
        st.warning("Ollama is not running. Start it with `ollama serve` then reload.")
        st.stop()

    _models = list_models()
    if not _models:
        st.warning("No Ollama models found. Run `ollama pull gemma2` to install one.")
        st.stop()

    _ai_model = st.selectbox("Model", _models, key="ai_model_sel")

    ai_ext, ai_int = st.tabs(["External assumptions", "Internal tracker"])

    with ai_ext:
        all_ext   = load_all_rows()
        unass_ext = [r for r in all_ext if not r.get("ai_assessed_at")]
        ass_ext   = [r for r in all_ext if r.get("ai_assessed_at")]
        m1, m2 = st.columns(2)
        m1.metric("Total external assumptions", len(all_ext))
        m2.metric("Assessed", len(ass_ext))

        b1, b2 = st.columns(2)
        run_ext_new = b1.button(f"▶ Assess {len(unass_ext)} new", disabled=not unass_ext, use_container_width=True)
        run_ext_all = b2.button(f"🔄 Re-assess all {len(all_ext)}", use_container_width=True, type="secondary")
        rows_to_run = unass_ext if run_ext_new else (all_ext if run_ext_all else [])

        if rows_to_run:
            pb = st.progress(0.0); st_txt = st.empty(); st_tbl = st.empty()
            done = []
            for res in assess_rows(_ai_model, rows_to_run, get_price_drift_map()):
                done.append(res)
                pb.progress(len(done) / len(rows_to_run))
                st_txt.markdown(f"Assessed **{len(done)}/{len(rows_to_run)}** — *{res['assumption'][:70]}*")
                st_tbl.dataframe(pd.DataFrame(done)[["assumption_id","assumption","classification","risk_level","rationale"]],
                                 hide_index=True, use_container_width=True)
            pb.progress(1.0)
            st_txt.success(f"Done — {len(done)} rows assessed.")
            st.rerun()

        if ass_ext:
            df_ass = pd.DataFrame(ass_ext)
            col1, col2 = st.columns(2)
            with col1:
                for cls, cnt in df_ass["ai_classification"].value_counts().items():
                    c, bg = _CLASS_BADGE_COLORS.get(cls, (BLUE_DIM, BLUE_DARK))
                    st.markdown(_badge(f"{cls}  ×{cnt}", c, bg), unsafe_allow_html=True)
            with col2:
                for lvl, cnt in df_ass["ai_risk_level"].value_counts().items():
                    c, bg = _RISK_BADGE_COLORS.get(lvl, (BLUE_DIM, BLUE_DARK))
                    st.markdown(_badge(f"{lvl}  ×{cnt}", c, bg), unsafe_allow_html=True)
            avail = [c for c in ["assumption_id","project_name","category","assumption",
                                  "ai_classification","ai_risk_level","ai_rationale","ai_assessed_at"]
                     if c in df_ass.columns]
            st.dataframe(df_ass[avail], hide_index=True, use_container_width=True)
            st.download_button("📥 Export (CSV)", df_ass[avail].to_csv(index=False).encode(),
                               "ai_external.csv", "text/csv")

    with ai_int:
        all_int   = load_all_tracker_rows()
        unass_int = [r for r in all_int if not r.get("ai_assessed_at")]
        ass_int   = [r for r in all_int if r.get("ai_assessed_at")]
        m1, m2 = st.columns(2)
        m1.metric("Total internal assumptions", len(all_int))
        m2.metric("Assessed", len(ass_int))

        b1, b2 = st.columns(2)
        run_int_new = b1.button(f"▶ Assess {len(unass_int)} new", disabled=not unass_int,
                                use_container_width=True, key="run_int_new")
        run_int_all = b2.button(f"🔄 Re-assess all {len(all_int)}", use_container_width=True,
                                type="secondary", key="run_int_all")
        rows_int = unass_int if run_int_new else (all_int if run_int_all else [])

        if rows_int:
            pb = st.progress(0.0); st_txt = st.empty(); st_tbl = st.empty()
            done = []
            for res in assess_tracker_rows(_ai_model, rows_int):
                done.append(res)
                pb.progress(len(done) / len(rows_int))
                st_txt.markdown(f"Assessed **{len(done)}/{len(rows_int)}** — *{res['title'][:70]}*")
                st_tbl.dataframe(pd.DataFrame(done)[["assumption_id","title","classification","risk_level","rationale"]],
                                 hide_index=True, use_container_width=True)
            pb.progress(1.0)
            st_txt.success(f"Done — {len(done)} rows assessed.")
            st.session_state.tracker_df = pd.DataFrame(load_tracker())
            st.rerun()

        if ass_int:
            df_ass_i = pd.DataFrame(ass_int)
            col1, col2 = st.columns(2)
            with col1:
                for cls, cnt in df_ass_i["ai_classification"].value_counts().items():
                    c, bg = _CLASS_BADGE_COLORS.get(cls, (BLUE_DIM, BLUE_DARK))
                    st.markdown(_badge(f"{cls}  ×{cnt}", c, bg), unsafe_allow_html=True)
            with col2:
                for lvl, cnt in df_ass_i["ai_risk_level"].value_counts().items():
                    c, bg = _RISK_BADGE_COLORS.get(lvl, (BLUE_DIM, BLUE_DARK))
                    st.markdown(_badge(f"{lvl}  ×{cnt}", c, bg), unsafe_allow_html=True)
            avail_i = [c for c in ["assumption_id","title","category","owner",
                                    "ai_classification","ai_risk_level","ai_rationale","ai_assessed_at"]
                       if c in df_ass_i.columns]
            st.dataframe(df_ass_i[avail_i], hide_index=True, use_container_width=True)
            st.download_button("📥 Export (CSV)", df_ass_i[avail_i].to_csv(index=False).encode(),
                               "ai_internal.csv", "text/csv")
