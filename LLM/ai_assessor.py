"""
ai_assessor.py — Ollama-powered batch assessment of assumption register rows.
Adds/populates ai_classification, ai_risk_level, ai_rationale, ai_assessed_at
columns in the assumptions table.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator, Optional

DB_PATH = Path(__file__).parent.parent / "Data" / "jet_engine_costs.db"

# ── Schema migration ───────────────────────────────────────────────────────────

AI_COLUMNS = [
    ("ai_classification", "TEXT"),   # "Assumption" | "Risk" | "Assumption+Risk"
    ("ai_risk_level",     "TEXT"),   # "High" | "Medium" | "Low" | "N/A"
    ("ai_rationale",      "TEXT"),   # one-sentence explanation
    ("ai_assessed_at",    "TEXT"),   # ISO timestamp
]


def ensure_ai_columns() -> None:
    """Add AI columns to both assumptions and assumption_tracker tables if missing."""
    con = sqlite3.connect(DB_PATH)
    for table in ("assumptions", "assumption_tracker"):
        try:
            existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
            for col_name, col_type in AI_COLUMNS:
                if col_name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass
    con.commit()
    con.close()


# ── Data helpers ───────────────────────────────────────────────────────────────

def load_unassessed() -> list[dict]:
    """Return rows that haven't been AI-assessed yet."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM assumptions WHERE ai_assessed_at IS NULL ORDER BY assumption_id"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def load_all_rows() -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM assumptions ORDER BY assumption_id").fetchall()
    con.close()
    return [dict(r) for r in rows]


def _save_assessment(assumption_id: int, classification: str,
                     risk_level: str, rationale: str) -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE assumptions SET ai_classification=?, ai_risk_level=?, "
        "ai_rationale=?, ai_assessed_at=? WHERE assumption_id=?",
        (classification, risk_level, rationale, datetime.now().isoformat(), assumption_id),
    )
    con.commit()
    con.close()


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_assessment_prompt(row: dict, price_drift_pct: Optional[float] = None) -> str:
    parts = [
        f'Text: "{row.get("assumption", "")}"',
        f'Type: {row.get("assumption_type", "")}',
        f'Category: {row.get("category", "")}',
        f'Location: {row.get("location", "")} (Internal=company-controlled, External=market/regulatory)',
    ]
    if row.get("ticker"):
        parts.append(f'Commodity ticker: {row["ticker"]}')
    if row.get("price_per_unit") is not None:
        parts.append(f'Assumed price: {row.get("currency", "")} {row["price_per_unit"]} per {row.get("unit", "")}')
    if price_drift_pct is not None:
        parts.append(f'Current market drift from assumed price: {price_drift_pct:+.1f}%')
    if row.get("total_cost") is not None:
        parts.append(f'Total cost exposure: {row.get("currency", "USD")} {row["total_cost"]:,.0f}')

    return "\n".join(parts)


_SYSTEM = """\
You are a senior risk analyst for jet engine manufacturing. Classify each item using STRICT rules.

CLASSIFICATION RULES — read carefully before deciding:
- Assumption: A stated belief or fixed value used in planning (e.g. a price, a lead time, a rate). \
It is NOT yet uncertain — it is a decision taken as given. If it turns out to be wrong, it causes a problem.
- Risk: An event or condition that has NOT happened yet but COULD occur and cause harm. \
It must be future-oriented and genuinely uncertain (e.g. "supplier may not deliver").
- Assumption+Risk: The item states a planning assumption AND that assumption also carries real uncertainty \
(e.g. price locked at X but market is volatile — both a planning fact and an unresolved uncertainty).

RISK LEVEL RULES:
- High: If wrong or if it occurs, the project is likely to miss schedule or exceed budget by >15%.
- Medium: Moderate cost or schedule impact (5–15%), recoverable with effort.
- Low: Minor impact (<5%), easily mitigated or absorbed.
- N/A: Informational only — no realistic path to cost or schedule harm (e.g. a compliance checkbox already met).

DO NOT default to Medium. Use High when the cost or schedule exposure is large. Use Low when impact is minor. \
Use N/A for informational or already-resolved items. Only use Assumption+Risk when BOTH conditions apply.

EXAMPLES:
Input: "Steel price assumed at $780/short ton, qty 80t" (material, 4% drift, USD 62400 exposure)
Output: {"classification": "Assumption+Risk", "risk_level": "High", "rationale": "Fixed price assumption on volatile commodity; £50k+ exposure if market moves further."}

Input: "Funding will be available on time per milestone schedule" (commercial, boolean)
Output: {"classification": "Assumption", "risk_level": "Low", "rationale": "Standard contractual assumption; funding mechanism already agreed."}

Input: "Autoclave availability — current schedule adherence 80% vs 95% baseline" (commercial, -16% drift)
Output: {"classification": "Risk", "risk_level": "High", "rationale": "Significant schedule slippage on shared resource; fan blade output directly impacted."}

Input: "Inflation within central bank forecast range" (economic, informational)
Output: {"classification": "Assumption", "risk_level": "Low", "rationale": "Broad macro assumption; marginal effect on project costs within planning tolerance."}

NOW classify the item below. Respond with a single JSON object — no markdown, no extra text.
{"classification": "...", "risk_level": "...", "rationale": "..."}
classification: Assumption | Risk | Assumption+Risk
risk_level: High | Medium | Low | N/A
rationale: one sentence, max 25 words.\
"""

_JSON_RE = re.compile(r'\{[^{}]+\}', re.DOTALL)
_VALID_CLASS = {"Assumption", "Risk", "Assumption+Risk"}
_VALID_RISK = {"High", "Medium", "Low", "N/A"}


def _parse_response(text: str) -> tuple[str, str, str]:
    """Extract classification, risk_level, rationale from model output. Returns defaults on failure."""
    # Try to find a JSON block even if model adds surrounding text
    match = _JSON_RE.search(text)
    if match:
        try:
            data = json.loads(match.group())
            cls  = data.get("classification", "").strip()
            risk = data.get("risk_level", "").strip()
            rat  = data.get("rationale", "").strip()
            if cls in _VALID_CLASS and risk in _VALID_RISK and rat:
                return cls, risk, rat
        except (json.JSONDecodeError, KeyError):
            pass
    return "Assumption", "N/A", "Could not parse AI response."


# ── Main batch assessor ────────────────────────────────────────────────────────

def assess_rows(
    model: str,
    rows: list[dict],
    price_drift_map: Optional[dict] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Generator[dict, None, None]:
    """
    Assess each row via Ollama. Yields result dicts as they complete.
    progress_cb(current, total, assumption_text) called after each row.
    price_drift_map: {ticker: drift_pct} for enriching material rows.
    """
    from ollama_client import chat_complete   # local import to avoid circular deps

    total = len(rows)
    for i, row in enumerate(rows):
        drift = None
        if price_drift_map and row.get("ticker"):
            drift = price_drift_map.get(row["ticker"])

        user_msg = _build_assessment_prompt(row, drift)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_msg},
        ]

        response = chat_complete(model, messages)
        classification, risk_level, rationale = _parse_response(response)
        _save_assessment(row["assumption_id"], classification, risk_level, rationale)

        result = {
            "assumption_id": row["assumption_id"],
            "assumption":    row.get("assumption", ""),
            "classification": classification,
            "risk_level":    risk_level,
            "rationale":     rationale,
        }

        if progress_cb:
            progress_cb(i + 1, total, str(row.get("assumption", ""))[:60])

        yield result


def _build_tracker_prompt(row: dict) -> str:
    """Build assessment prompt for an internal tracker row."""
    drift_net = (float(row.get("internal_drift_pct") or 0) + float(row.get("external_drift_pct") or 0)) * 100
    parts = [
        f'Title: "{row.get("title","")}"',
        f'Description: "{row.get("description","")}"',
        f'Category: {row.get("category","")}',
        f'Owner: {row.get("owner","")}',
        f'Baseline: {row.get("baseline_value","")} {row.get("unit","")} → Current: {row.get("current_value","")} {row.get("unit","")}',
        f'Net drift: {drift_net:+.1f}%',
        f'Confidence score: {row.get("confidence_score","")}/100',
        f'Status: {row.get("status","")}',
    ]
    return "\n".join(parts)


def _save_tracker_assessment(assumption_id: str, classification: str,
                              risk_level: str, rationale: str) -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE assumption_tracker SET ai_classification=?, ai_risk_level=?, "
        "ai_rationale=?, ai_assessed_at=? WHERE assumption_id=?",
        (classification, risk_level, rationale, datetime.now().isoformat(), assumption_id),
    )
    con.commit()
    con.close()


def assess_single_tracker_row(model: str, row: dict) -> dict:
    """Assess one internal tracker row synchronously. Returns result dict."""
    from ollama_client import chat_complete
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": _build_tracker_prompt(row)},
    ]
    response = chat_complete(model, messages)
    classification, risk_level, rationale = _parse_response(response)
    _save_tracker_assessment(str(row["assumption_id"]), classification, risk_level, rationale)
    return {"assumption_id": row["assumption_id"], "classification": classification,
            "risk_level": risk_level, "rationale": rationale}


def load_unassessed_tracker() -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM assumption_tracker WHERE ai_assessed_at IS NULL ORDER BY assumption_id"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def load_all_tracker_rows() -> list[dict]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM assumption_tracker ORDER BY assumption_id").fetchall()
    con.close()
    return [dict(r) for r in rows]


def assess_tracker_rows(
    model: str,
    rows: list[dict],
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Generator[dict, None, None]:
    """Batch assess internal tracker rows. Yields result dicts."""
    from ollama_client import chat_complete
    total = len(rows)
    for i, row in enumerate(rows):
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": _build_tracker_prompt(row)},
        ]
        response = chat_complete(model, messages)
        classification, risk_level, rationale = _parse_response(response)
        _save_tracker_assessment(str(row["assumption_id"]), classification, risk_level, rationale)
        result = {"assumption_id": row["assumption_id"], "title": row.get("title", ""),
                  "classification": classification, "risk_level": risk_level, "rationale": rationale}
        if progress_cb:
            progress_cb(i + 1, total, str(row.get("title", ""))[:60])
        yield result


def get_price_drift_map() -> dict:
    """Build {ticker: drift_pct} from live prices vs assumed prices in assumptions table."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Live prices by ticker
    live = con.execute("""
        SELECT c.ticker, ps.price AS live_usd
        FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id = c.id
        WHERE ps.id IN (SELECT MAX(id) FROM price_snapshots GROUP BY commodity_id)
          AND c.ticker IS NOT NULL AND c.ticker != ''
    """).fetchall()

    # GBP/USD
    fx = con.execute("""
        SELECT ps.price FROM price_snapshots ps
        JOIN commodities c ON ps.commodity_id = c.id
        WHERE c.name IN ('GBP/USD', 'GBPUSD=X')
        ORDER BY ps.id DESC LIMIT 1
    """).fetchone()
    gbp_rate = float(fx[0]) if fx else 1.27

    # Assumed prices from assumptions table
    assumed = con.execute(
        "SELECT ticker, price_per_unit, currency FROM assumptions WHERE ticker != '' AND ticker IS NOT NULL"
    ).fetchall()
    con.close()

    # Normalise tickers: assumptions use "ALI", commodities use "ALI=F"
    # Build lookup that matches both forms
    live_map: dict[str, float] = {}
    for r in live:
        t = r["ticker"]
        live_map[t] = float(r["live_usd"])
        # Also store without the trailing "=F" suffix
        if t.endswith("=F"):
            live_map[t[:-2]] = float(r["live_usd"])

    drift_map: dict[str, float] = {}
    for r in assumed:
        ticker = r["ticker"]
        if not ticker or ticker not in live_map:
            continue
        assumed_usd = float(r["price_per_unit"] or 0)
        if str(r["currency"]).upper() == "GBP":
            assumed_usd *= gbp_rate
        if assumed_usd > 0:
            drift_map[ticker] = (live_map[ticker] - assumed_usd) / assumed_usd * 100.0

    return drift_map
