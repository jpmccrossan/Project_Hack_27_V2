"""
Deliverability Dashboard — per-project budget tracking, confidence, and risk status.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = str(Path(__file__).parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Ensure schema is always up to date — safe to run every time (uses IF NOT EXISTS)
try:
    from Database.db_setup import build as _db_build
    _db_build()
except Exception:
    pass

from utils.shared import (
    BLUE, BLUE_DIM, BLUE_DARK, GOLD, BG, CARD_BG, GREEN, AMBER, RED,
    jic_label, get_gbp_usd, db_query as _q, db_execute as _execute,
    inject_theme,
)

st.set_page_config(page_title="Deliverability", page_icon="🎯", layout="wide")
inject_theme()


def _log_project_change(project_id: int, field: str, old_val, new_val,
                         user: str = "user", reason: str = "") -> None:
    _execute(
        "INSERT INTO project_audit_log (project_id, timestamp, field_name, old_value, new_value, user, change_reason) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, datetime.now().isoformat(), field, str(old_val), str(new_val), user, reason),
    )


def _load_confidence_history(project_id: int) -> pd.DataFrame:
    return _q(
        "SELECT timestamp, new_value AS confidence FROM project_audit_log "
        "WHERE project_id=? AND field_name='confidence_score' ORDER BY timestamp",
        (project_id,)
    )


def _load_budget_history(project_id: int) -> pd.DataFrame:
    return _q(
        "SELECT timestamp, new_value AS budget_gbp FROM project_audit_log "
        "WHERE project_id=? AND field_name='budget_gbp' ORDER BY timestamp",
        (project_id,)
    )


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_projects() -> pd.DataFrame:
    return _q("SELECT * FROM projects ORDER BY project_id")


def _load_project_costs() -> pd.DataFrame:
    """Sum total_cost from assumptions per project (external costs)."""
    return _q("""
        SELECT project_id,
               SUM(COALESCE(total_cost, 0)) AS ext_cost_usd,
               COUNT(*) AS n_assumptions,
               SUM(CASE WHEN assumption_type='material' THEN COALESCE(total_cost,0) ELSE 0 END) AS material_cost_usd
        FROM assumptions
        GROUP BY project_id
    """)


def _load_price_drift() -> pd.DataFrame:
    """Average price drift for material assumptions per project, with GBP→USD conversion and outlier cap."""
    # Get live GBP/USD rate from DB to normalise GBP-priced assumptions
    fx = _q("""
        SELECT ps.price FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id=c.id
        WHERE c.name IN ('GBP/USD','GBPUSD=X') ORDER BY ps.id DESC LIMIT 1
    """)
    gbp_rate = float(fx["price"].iloc[0]) if not fx.empty else 1.35

    df = _q("""
        SELECT a.project_id,
               a.price_per_unit,
               a.currency,
               ps.price AS live_usd
        FROM assumptions a
        LEFT JOIN commodities c ON (c.ticker = a.ticker || '=F' OR c.ticker = a.ticker)
        LEFT JOIN price_snapshots ps ON ps.commodity_id = c.id
            AND ps.id = (SELECT MAX(id) FROM price_snapshots WHERE commodity_id = c.id)
        WHERE a.ticker != '' AND a.ticker IS NOT NULL
          AND a.price_per_unit > 0 AND ps.price IS NOT NULL
    """)

    if df.empty:
        return _q("SELECT project_id, NULL AS avg_drift_pct, 0 AS n_material FROM assumptions GROUP BY project_id")

    # Convert assumed price to USD for fair comparison
    df["assumed_usd"] = df.apply(
        lambda r: float(r["price_per_unit"]) * gbp_rate
        if str(r.get("currency", "")).upper() == "GBP"
        else float(r["price_per_unit"]),
        axis=1,
    )
    df = df[df["assumed_usd"] > 0].copy()
    df["drift_pct"] = (df["live_usd"] - df["assumed_usd"]) / df["assumed_usd"] * 100.0
    # Cap outliers: anything beyond ±150% is likely a data error
    df["drift_pct"] = df["drift_pct"].clip(-150, 150)

    result = (
        df.groupby("project_id")
        .agg(avg_drift_pct=("drift_pct", "mean"), n_material=("drift_pct", "count"))
        .reset_index()
    )
    return result


def _load_internal_risks(project_name: str) -> pd.DataFrame:
    """Internal tracker rows that mention the project or match by name."""
    return _q("""
        SELECT assumption_id, title, category, status, confidence_score,
               net_drift_pct, review_status, internal_drift_pct, external_drift_pct
        FROM assumption_tracker
        WHERE LOWER(description) LIKE ?
           OR LOWER(title) LIKE ?
        ORDER BY confidence_score
    """, (f"%{project_name.lower()}%", f"%{project_name.lower()}%"))


def _load_ai_risks(project_id: int) -> pd.DataFrame:
    return _q("""
        SELECT assumption, ai_classification, ai_risk_level, ai_rationale
        FROM assumptions
        WHERE project_id=? AND ai_classification IS NOT NULL
          AND ai_risk_level IN ('High','Medium')
        ORDER BY CASE ai_risk_level WHEN 'High' THEN 0 ELSE 1 END
    """, (project_id,))


# _get_gbp_rate replaced by get_gbp_usd() from utils.shared


# ── RAG status logic ──────────────────────────────────────────────────────────

# jic_label imported from utils.shared


def _rag(cost_gbp: float, budget: float, threshold_pct: float) -> tuple[str, str, str]:
    """Return (label, colour, icon) based on cost vs budget ± threshold."""
    if budget <= 0:
        return "No budget set", BLUE_DIM, "—"
    pct_used = (cost_gbp / budget) * 100
    upper = 100 + threshold_pct
    warn  = 100 + threshold_pct * 0.6
    if pct_used > upper:
        return f"🔴 Over budget — {pct_used:.0f}% of budget used (limit: {upper:.0f}%)", RED, "🔴"
    if pct_used > warn:
        return f"🟡 At risk — {pct_used:.0f}% of budget used (warning: >{warn:.0f}%)", AMBER, "🟡"
    return f"🟢 On track — {pct_used:.0f}% of budget used", GREEN, "🟢"


def _confidence_color(score: int) -> str:
    return jic_label(score)[1]


def _deliverability_score(confidence: int, rag_color: str, avg_drift: float | None) -> int:
    """
    Composite deliverability score 0-100:
      Base = composite confidence score (avg of latest per reviewer role, else project value)
      − 20 if over budget (RAG = red), − 10 if at-risk (amber)
      − 10 if market drift > 20%, − 5 if drift > 10%
    """
    base = confidence
    if rag_color == RED:     base -= 20
    elif rag_color == AMBER: base -= 10
    if avg_drift and abs(avg_drift) > 20:
        base -= 10
    elif avg_drift and abs(avg_drift) > 10:
        base -= 5
    return max(0, min(100, base))


# ── Card renderer ─────────────────────────────────────────────────────────────

def _project_card(proj: dict, cost_row: dict, drift_row: dict, gbp_rate: float) -> None:
    ext_usd   = cost_row.get("ext_cost_usd") or 0.0
    ext_gbp   = ext_usd / gbp_rate
    budget    = float(proj.get("budget_gbp") or 0)
    thresh    = float(proj.get("budget_threshold_pct") or 10)
    conf      = int(proj.get("confidence_score") or 70)
    avg_drift = drift_row.get("avg_drift_pct")

    rag_label, rag_color, rag_icon = _rag(ext_gbp, budget, thresh)
    conf_jic, conf_color = jic_label(conf)
    deliv = _deliverability_score(conf, rag_color, avg_drift)
    deliv_jic, deliv_color = jic_label(deliv)

    budget_str = f"£{budget:,.0f}" if budget > 0 else "Not set"
    cost_str   = f"£{ext_gbp:,.0f}" if ext_gbp > 0 else "£0"
    drift_str  = f"{avg_drift:+.1f}%" if avg_drift is not None else "—"
    drift_color = RED if avg_drift and abs(avg_drift) > 15 else AMBER if avg_drift and abs(avg_drift) > 5 else BLUE_DIM
    status_txt = str(proj.get("status") or "Active")

    st.markdown(f"""
    <div style='background:{CARD_BG};border:2px solid {rag_color};border-radius:12px;
                padding:18px 20px 14px;margin-bottom:12px;'>
      <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
        <div>
          <div style='font-size:0.62rem;color:{BLUE_DIM};text-transform:uppercase;
                      letter-spacing:0.12em;margin-bottom:2px;'>Project {proj["project_id"]}</div>
          <div style='font-size:1.1rem;font-weight:700;color:#FFFFFF;'>{proj["project_name"]}</div>
          <div style='font-size:0.78rem;color:{GOLD};margin-top:2px;'>
            👤 {proj.get("customer_name","—")}
          </div>
        </div>
        <div style='text-align:right;max-width:200px;'>
          <div style='font-size:0.78rem;font-weight:700;color:{rag_color};'>{rag_label}</div>
          <div style='font-size:0.62rem;color:{BLUE_DIM};margin-top:2px;'>Status: {status_txt}</div>
        </div>
      </div>

      <div style='display:flex;gap:16px;margin-top:14px;flex-wrap:wrap;'>
        <div style='flex:1;min-width:90px;'>
          <div style='font-size:0.6rem;color:{BLUE_DIM};text-transform:uppercase;
                      letter-spacing:0.08em;'>Budget</div>
          <div style='font-size:1.1rem;font-weight:700;color:#FFFFFF;'>{budget_str}</div>
          <div style='font-size:0.62rem;color:{BLUE_DIM};'>±{thresh:.0f}% threshold</div>
        </div>
        <div style='flex:1;min-width:90px;'>
          <div style='font-size:0.6rem;color:{BLUE_DIM};text-transform:uppercase;
                      letter-spacing:0.08em;'>Current Cost</div>
          <div style='font-size:1.1rem;font-weight:700;color:{rag_color};'>{cost_str}</div>
          <div style='font-size:0.62rem;color:{BLUE_DIM};'>from {int(cost_row.get("n_assumptions",0))} assumptions</div>
        </div>
        <div style='flex:1;min-width:90px;'>
          <div style='font-size:0.6rem;color:{BLUE_DIM};text-transform:uppercase;
                      letter-spacing:0.08em;'>Market Drift</div>
          <div style='font-size:1.1rem;font-weight:700;color:{drift_color};'>{drift_str}</div>
          <div style='font-size:0.62rem;color:{BLUE_DIM};'>vs assumed prices</div>
        </div>
        <div style='flex:1;min-width:110px;'>
          <div style='font-size:0.6rem;color:{BLUE_DIM};text-transform:uppercase;
                      letter-spacing:0.08em;'>Confidence</div>
          <div style='font-size:1.1rem;font-weight:700;color:{conf_color};'>{conf}/100</div>
          <div style='font-size:0.62rem;color:{conf_color};font-style:italic;'>{conf_jic}</div>
        </div>
        <div style='flex:1;min-width:110px;'>
          <div style='font-size:0.6rem;color:{BLUE_DIM};text-transform:uppercase;
                      letter-spacing:0.08em;'>Deliverability</div>
          <div style='font-size:1.1rem;font-weight:700;color:{deliv_color};'>{deliv}/100</div>
          <div style='font-size:0.62rem;color:{deliv_color};font-style:italic;'>{deliv_jic}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("# 🎯 Deliverability Dashboard")
st.caption(
    "Per-project view: budget vs cost, market price drift, confidence score, and composite deliverability. "
    "All data feeds from the single shared database — external market assumptions + internal risk tracker."
)

projects  = _load_projects()
costs     = _load_project_costs()
drifts    = _load_price_drift()
gbp_rate  = get_gbp_usd()

cost_map  = {int(r["project_id"]): r for _, r in costs.iterrows()}
drift_map = {int(r["project_id"]): r for _, r in drifts.iterrows()}

# ── Portfolio summary metrics ─────────────────────────────────────────────────
if not projects.empty:
    total_budget = float(projects["budget_gbp"].sum())
    total_cost   = sum(
        (cost_map.get(int(r["project_id"]), {}).get("ext_cost_usd") or 0) / gbp_rate
        for _, r in projects.iterrows()
    )
    avg_conf = float(projects["confidence_score"].mean())
    at_risk  = sum(
        1 for _, r in projects.iterrows()
        if _rag(
            (cost_map.get(int(r["project_id"]), {}).get("ext_cost_usd") or 0) / gbp_rate,
            float(r["budget_gbp"] or 0),
            float(r["budget_threshold_pct"] or 10),
        )[1] in (RED, AMBER)
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Projects", len(projects))
    m2.metric("Total budget", f"£{total_budget:,.0f}")
    m3.metric("Total cost (market)", f"£{total_cost:,.0f}",
              delta=f"{'over' if total_cost>total_budget else 'under'} by £{abs(total_cost-total_budget):,.0f}")
    m4.metric("Portfolio confidence", f"{avg_conf:.0f}/100")
    m5.metric("At risk / over threshold", at_risk,
              delta="Review needed" if at_risk else None, delta_color="inverse")

with st.expander("ℹ️ How scores are calculated"):
    st.markdown(f"""
**Confidence score** (0–100)
Composite of the latest review submissions by each reviewer role (General Project Working, Project Manager,
C Suite). Stored value = mean of the three roles' most recent scores. Where only one role has reviewed,
that score is used directly.

| Score | JIC Level |
|-------|-----------|
| 0–20  | Critical |
| 21–35 | Highly Unlikely |
| 36–50 | Unlikely |
| 51–65 | Realistic Possibility |
| 66–80 | Likely |
| 81–92 | Highly Likely |
| 93–100 | Almost Certain |

**Deliverability score** (0–100)
```
Deliverability = Confidence score
  − 20  if cost > budget + threshold (over budget)
  − 10  if cost > budget + 60% of threshold (at risk)
  − 10  if avg market drift > ±20%
  −  5  if avg market drift > ±10%
```
Clamped to 0–100. The same JIC scale applies.

**Budget RAG status**
- Green: cost ≤ budget + threshold
- Amber: cost > budget + 60% of threshold
- Red: cost > budget + full threshold

**Market drift**
Live commodity price vs assumed price in the assumptions register, converted to USD for a fair comparison.
Capped at ±150% to exclude data anomalies. Averaged across all material assumptions for the project.
    """)

st.divider()

# ── Sidebar — filters and edit ────────────────────────────────────────────────
with st.sidebar:
    status_opts = sorted(projects["status"].unique().tolist()) if not projects.empty else []
    sel_status  = st.multiselect("Status", status_opts, default=status_opts)
    sel_cust    = st.multiselect(
        "Customer",
        sorted(projects["customer_name"].dropna().unique().tolist()),
        default=sorted(projects["customer_name"].dropna().unique().tolist()),
    )
    st.divider()
    view_mode = st.radio("Layout", ["Cards", "Table"], horizontal=True)

tab_overview, tab_detail, tab_edit = st.tabs(["📊 Portfolio Overview", "🔍 Project Detail", "✏️ Edit Projects"])

# ── Portfolio overview ────────────────────────────────────────────────────────
with tab_overview:
    # ── Threshold key ─────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style='background:{CARD_BG};border:1px solid {BLUE_DARK};border-radius:8px;
                padding:10px 18px;margin-bottom:14px;display:flex;gap:28px;flex-wrap:wrap;
                align-items:center;'>
      <div style='font-size:0.62rem;color:{BLUE_DIM};text-transform:uppercase;
                  letter-spacing:0.1em;'>Budget status key</div>
      <div>
        <span style='color:{GREEN};font-weight:700;'>🟢 On track</span>
        <span style='color:{BLUE_DIM};font-size:0.75rem;'> — cost within budget</span>
      </div>
      <div>
        <span style='color:{AMBER};font-weight:700;'>🟡 At risk</span>
        <span style='color:{BLUE_DIM};font-size:0.75rem;'> — cost &gt; budget + 60% of threshold</span>
      </div>
      <div>
        <span style='color:{RED};font-weight:700;'>🔴 Over budget</span>
        <span style='color:{BLUE_DIM};font-size:0.75rem;'> — cost &gt; budget + full threshold</span>
      </div>
      <div style='color:{BLUE_DIM};font-size:0.72rem;'>
        Threshold is set per project (e.g. ±10%). Budget % = external market cost ÷ budget.
      </div>
    </div>
    """, unsafe_allow_html=True)

    filtered = projects.copy()
    if sel_status:
        filtered = filtered[filtered["status"].isin(sel_status)]
    if sel_cust:
        filtered = filtered[filtered["customer_name"].isin(sel_cust)]

    if filtered.empty:
        st.info("No projects match the current filters.")
    elif view_mode == "Cards":
        for _, proj in filtered.iterrows():
            pid = int(proj["project_id"])
            _project_card(
                proj.to_dict(),
                cost_map.get(pid, {}),
                drift_map.get(pid, {}),
                gbp_rate,
            )
    else:
        # Table view
        _STATUS_ICON = {
            "Active": "🟢", "Monitor": "🟡", "At Risk": "🔴",
            "On Hold": "⚫", "Complete": "✅",
        }
        rows = []
        for _, proj in filtered.iterrows():
            pid     = int(proj["project_id"])
            ext_usd = cost_map.get(pid, {}).get("ext_cost_usd") or 0
            ext_gbp = ext_usd / gbp_rate
            budget  = float(proj.get("budget_gbp") or 0)
            thresh  = float(proj.get("budget_threshold_pct") or 10)
            conf    = int(proj.get("confidence_score") or 70)
            drift   = drift_map.get(pid, {}).get("avg_drift_pct")
            rag_lbl, rag_col, rag_icon = _rag(ext_gbp, budget, thresh)
            rag_color                  = rag_col
            deliv                      = _deliverability_score(conf, rag_color, drift)
            conf_jic,  _               = jic_label(conf)
            deliv_jic, _               = jic_label(deliv)
            status_txt                 = str(proj.get("status", "Active"))
            rows.append({
                "Project":        proj["project_name"],
                "Customer":       proj.get("customer_name", "—"),
                "Status":         f"{_STATUS_ICON.get(status_txt, '⚪')} {status_txt}",
                "Budget (£)":     budget,
                "Cost (£)":       round(ext_gbp, 0),
                "Budget status":  rag_lbl,
                "Mkt drift":      f"{drift:+.1f}%" if drift is not None else "—",
                "Confidence":     conf,
                "Conf. level":    conf_jic,
                "Deliverability": deliv,
                "Deliv. level":   deliv_jic,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={
                         "Budget (£)":     st.column_config.NumberColumn(format="£%.0f"),
                         "Cost (£)":       st.column_config.NumberColumn(format="£%.0f"),
                         "Confidence":     st.column_config.ProgressColumn(
                             "Confidence", min_value=0, max_value=100),
                         "Deliverability": st.column_config.ProgressColumn(
                             "Deliverability", min_value=0, max_value=100),
                         "Conf. level":    st.column_config.TextColumn("Conf. level"),
                         "Deliv. level":   st.column_config.TextColumn("Deliv. level"),
                     })

# ── Project detail ────────────────────────────────────────────────────────────
with tab_detail:
    if projects.empty:
        st.info("No projects found.")
    else:
        proj_options = {
            int(r["project_id"]): f"{r['project_name']} — {r.get('customer_name','')}"
            for _, r in projects.iterrows()
        }
        sel_pid = st.selectbox("Select project", list(proj_options.keys()),
                               format_func=lambda x: proj_options[x])
        proj = projects[projects["project_id"] == sel_pid].iloc[0].to_dict()
        cost_r  = cost_map.get(sel_pid, {})
        drift_r = drift_map.get(sel_pid, {})

        _project_card(proj, cost_r, drift_r, gbp_rate)

        # External assumptions for this project
        ext_asmp = _q(
            "SELECT assumption_id, assumption_type, location, assumption, "
            "ticker, price_per_unit, currency, unit, qty, total_cost, "
            "ai_classification, ai_risk_level, ai_rationale "
            "FROM assumptions WHERE project_id=? ORDER BY assumption_type, assumption_id",
            (sel_pid,)
        )

        if not ext_asmp.empty:
            st.markdown("#### External Assumptions")
            high_risk = ext_asmp[ext_asmp["ai_risk_level"] == "High"]
            if not high_risk.empty:
                st.warning(f"⚠ {len(high_risk)} High-risk assumption(s) flagged by AI for this project.")

            st.dataframe(ext_asmp, hide_index=True, use_container_width=True,
                         column_config={
                             "total_cost": st.column_config.NumberColumn("Total cost (USD)", format="$%.0f"),
                             "price_per_unit": st.column_config.NumberColumn("Assumed price", format="%.3f"),
                             "ai_risk_level": st.column_config.TextColumn("AI Risk"),
                             "ai_classification": st.column_config.TextColumn("AI Class"),
                             "ai_rationale": st.column_config.TextColumn("AI Notes"),
                         })

        # Confidence + budget history charts
        conf_hist = _load_confidence_history(sel_pid)
        budg_hist = _load_budget_history(sel_pid)

        if not conf_hist.empty or not budg_hist.empty:
            st.markdown("#### Confidence & Budget History")
            ch1, ch2 = st.columns(2)
            with ch1:
                if not conf_hist.empty:
                    conf_hist["confidence"] = pd.to_numeric(conf_hist["confidence"], errors="coerce")
                    conf_hist["timestamp"]  = pd.to_datetime(conf_hist["timestamp"], format="ISO8601")
                    st.markdown("**Confidence score over time**")
                    st.line_chart(conf_hist.set_index("timestamp")["confidence"],
                                  use_container_width=True, height=200)
            with ch2:
                if not budg_hist.empty:
                    budg_hist["budget_gbp"] = pd.to_numeric(budg_hist["budget_gbp"], errors="coerce")
                    budg_hist["timestamp"]  = pd.to_datetime(budg_hist["timestamp"], format="ISO8601")
                    st.markdown("**Budget (£) revisions over time**")
                    st.line_chart(budg_hist.set_index("timestamp")["budget_gbp"],
                                  use_container_width=True, height=200)

        # Audit log for this project
        proj_log = _q(
            "SELECT timestamp, field_name, old_value, new_value, user, change_reason "
            "FROM project_audit_log WHERE project_id=? ORDER BY timestamp DESC LIMIT 30",
            (sel_pid,)
        )
        if not proj_log.empty:
            with st.expander("📜 Change history (last 30 entries)"):
                st.dataframe(proj_log, hide_index=True, use_container_width=True)

        # Internal risks linked to this project
        ai_risks = _load_ai_risks(sel_pid)
        if not ai_risks.empty:
            st.markdown("#### AI-flagged Risks")
            for _, r in ai_risks.iterrows():
                color = RED if r["ai_risk_level"] == "High" else AMBER
                st.markdown(
                    f"<div style='background:{CARD_BG};border-left:3px solid {color};"
                    f"padding:8px 14px;border-radius:4px;margin:4px 0;'>"
                    f"<span style='color:{color};font-weight:700;font-size:0.72rem;'>"
                    f"{r['ai_risk_level'].upper()} · {r['ai_classification']}</span>"
                    f"<div style='color:#D0E8FF;font-size:0.85rem;margin-top:2px;'>{r['assumption']}</div>"
                    f"<div style='color:{BLUE_DIM};font-size:0.72rem;margin-top:2px;'>{r['ai_rationale']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

# ── Edit projects ─────────────────────────────────────────────────────────────

REVIEWER_ROLES = ["General Project Working", "Project Manager", "C Suite"]


def _load_role_confidence(project_id: int) -> pd.DataFrame:
    return _q("""
        SELECT user AS role,
               CAST(new_value AS REAL) AS confidence,
               timestamp
        FROM project_audit_log
        WHERE project_id=? AND field_name='confidence_score'
          AND user IN ('General Project Working','Project Manager','C Suite')
        ORDER BY timestamp
    """, (project_id,))


with tab_edit:
    st.markdown("#### Project Review")
    st.caption(
        "Log your confidence assessment and status update. "
        "Project name, customer, and budget are read-only — contact the portfolio manager to amend these."
    )

    if projects.empty:
        st.info("No projects found.")
    else:
        sel_edit = st.selectbox(
            "Select project",
            projects["project_id"].tolist(),
            format_func=lambda x: projects[projects["project_id"]==x]["project_name"].iloc[0],
            key="edit_proj_sel",
        )
        edit_row = projects[projects["project_id"] == sel_edit].iloc[0]

        # ── Read-only project info panel ──────────────────────────────────────
        st.markdown(f"""
        <div style='background:{CARD_BG};border:1px solid {BLUE_DIM};border-radius:10px;
                    padding:16px 20px 12px;margin-bottom:16px;'>
          <div style='display:flex;gap:36px;flex-wrap:wrap;align-items:flex-start;'>
            <div>
              <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;
                          letter-spacing:0.1em;margin-bottom:2px;'>Project</div>
              <div style='font-size:1rem;font-weight:700;color:#FFFFFF;'>
                {edit_row.get("project_name","")}
              </div>
            </div>
            <div>
              <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;
                          letter-spacing:0.1em;margin-bottom:2px;'>Customer</div>
              <div style='font-size:1rem;font-weight:700;color:{GOLD};'>
                {edit_row.get("customer_name","—")}
              </div>
            </div>
            <div>
              <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;
                          letter-spacing:0.1em;margin-bottom:2px;'>Budget</div>
              <div style='font-size:1rem;font-weight:700;color:#FFFFFF;'>
                £{float(edit_row.get("budget_gbp") or 0):,.0f}
              </div>
            </div>
            <div>
              <div style='font-size:0.58rem;color:{BLUE_DIM};text-transform:uppercase;
                          letter-spacing:0.1em;margin-bottom:2px;'>Threshold</div>
              <div style='font-size:1rem;font-weight:700;color:#FFFFFF;'>
                ±{float(edit_row.get("budget_threshold_pct") or 10):.0f}%
              </div>
            </div>
          </div>
          <div style='margin-top:10px;font-size:0.68rem;color:{BLUE_DIM};'>
            🔒 Read-only fields — contact the portfolio manager to request changes.
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Editable review form ───────────────────────────────────────────────
        with st.form("edit_project"):
            fc1, fc2 = st.columns(2)
            reviewer_role = fc1.selectbox("Your role", REVIEWER_ROLES)
            new_status    = fc2.selectbox(
                "Project status",
                ["Active", "Monitor", "At Risk", "On Hold", "Complete"],
                index=(["Active", "Monitor", "At Risk", "On Hold", "Complete"]
                       .index(str(edit_row.get("status", "Active")))
                       if str(edit_row.get("status", "Active"))
                       in ["Active", "Monitor", "At Risk", "On Hold", "Complete"] else 0),
            )

            new_conf = st.slider(
                "Confidence score — your assessment",
                0, 100,
                int(edit_row.get("confidence_score") or 70),
                help="0 = no confidence, 100 = certain. Your score is logged separately and "
                     "combined with other roles to form the composite.",
            )

            change_reason = st.text_input(
                "Review notes  ✱ required",
                placeholder="e.g. Post-supplier meeting — materials costs confirmed stable",
            )

            if st.form_submit_button("💾 Log review"):
                if not change_reason.strip():
                    st.error("Please enter review notes before saving.")
                else:
                    reason_txt = change_reason.strip()
                    old_status = str(edit_row.get("status") or "Active")
                    old_conf   = str(int(edit_row.get("confidence_score") or 70))

                    if old_status != new_status:
                        _log_project_change(int(sel_edit), "status", old_status, new_status,
                                            user=reviewer_role, reason=reason_txt)
                    _log_project_change(int(sel_edit), "confidence_score", old_conf, str(new_conf),
                                        user=reviewer_role, reason=reason_txt)

                    # Recompute composite confidence from latest score per role, fall back to this value
                    latest_per_role = _q("""
                        SELECT user, CAST(new_value AS REAL) AS confidence
                        FROM project_audit_log
                        WHERE project_id=? AND field_name='confidence_score'
                          AND user IN ('General Project Working','Project Manager','C Suite')
                        GROUP BY user HAVING MAX(timestamp)
                    """, (int(sel_edit),))
                    composite = int(round(
                        latest_per_role["confidence"].mean()
                        if not latest_per_role.empty else new_conf
                    ))

                    _execute(
                        "UPDATE projects SET status=?, confidence_score=?, updated_at=? WHERE project_id=?",
                        (new_status, composite, datetime.now().isoformat(), int(sel_edit)),
                    )
                    st.success(
                        f"Review logged by **{reviewer_role}**. "
                        f"Composite confidence updated to **{composite}/100**."
                    )
                    st.rerun()

        # ── Per-role confidence breakdown ──────────────────────────────────────
        st.divider()
        st.markdown("#### Confidence by Reviewer Role")

        role_df = _load_role_confidence(int(sel_edit))

        if role_df.empty:
            st.info("No role-based reviews logged yet for this project. Submit the form above to start tracking.")
        else:
            role_df["confidence"] = pd.to_numeric(role_df["confidence"], errors="coerce")
            role_df["timestamp"]  = pd.to_datetime(role_df["timestamp"])

            # Latest and mean per role
            latest = (
                role_df.sort_values("timestamp")
                .groupby("role", as_index=False)
                .agg(latest=("confidence", "last"), mean=("confidence", "mean"), count=("confidence", "count"))
            )
            composite_score = int(round(latest["latest"].mean()))

            # Metric cards
            metric_cols = st.columns(len(latest) + 1)
            for i, (_, r) in enumerate(latest.iterrows()):
                delta_txt = f"avg {r['mean']:.0f} · {int(r['count'])} reviews"
                metric_cols[i].metric(r["role"], f"{int(r['latest'])}/100", delta=delta_txt)
            metric_cols[-1].metric("Composite (mean of roles)", f"{composite_score}/100")

            # Trend chart — Vega-Lite for dark-theme consistency
            if not role_df.empty:
                st.markdown("**Confidence trend by reviewer role**")
                role_colours = {
                    "General Project Working": "#4FC3F7",
                    "Project Manager":         "#C4A44A",
                    "C Suite":                 "#66BB6A",
                }
                vl_data = role_df[["timestamp", "role", "confidence"]].copy()
                vl_data["timestamp"] = vl_data["timestamp"].astype(str)
                vl_chart = {
                    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                    "background": "#06091A",
                    "height": 240,
                    "data": {"values": vl_data.to_dict(orient="records")},
                    "mark": {"type": "line", "point": True, "interpolate": "monotone"},
                    "encoding": {
                        "x": {"field": "timestamp", "type": "temporal",
                              "axis": {"labelColor": "#4FC3F7", "gridColor": "#0C1629", "title": None}},
                        "y": {"field": "confidence", "type": "quantitative",
                              "scale": {"domain": [0, 100]},
                              "axis": {"labelColor": "#4FC3F7", "gridColor": "#0C1629", "title": "Confidence"}},
                        "color": {
                            "field": "role", "type": "nominal",
                            "scale": {
                                "domain": list(role_colours.keys()),
                                "range":  list(role_colours.values()),
                            },
                            "legend": {"labelColor": "#4FC3F7", "titleColor": "#1A8CBF", "title": "Role"},
                        },
                        "tooltip": [
                            {"field": "role",       "title": "Role"},
                            {"field": "timestamp",  "type": "temporal", "title": "Date"},
                            {"field": "confidence", "title": "Confidence"},
                        ],
                    },
                }
                st.vega_lite_chart(vl_data, vl_chart, use_container_width=True)

        # ── All-project overview table ─────────────────────────────────────────
        st.divider()
        st.markdown("#### All Projects — Quick Overview")
        st.dataframe(
            projects[["project_id", "project_name", "customer_name", "budget_gbp",
                       "budget_threshold_pct", "confidence_score", "status"]],
            hide_index=True, use_container_width=True,
            column_config={
                "budget_gbp": st.column_config.NumberColumn("Budget (£)", format="£%.0f"),
                "budget_threshold_pct": st.column_config.NumberColumn("Threshold (%)", format="%.1f%%"),
                "confidence_score": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100),
            },
        )
