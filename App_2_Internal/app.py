from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import inspect
import re
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

from db import (
    init_db,
    load_assumptions,
    add_assumption,
    update_assumption,
    get_audit_history,
    seed_db_if_empty,
    reset_and_seed_data,
    delete_assumption_permanent,
    delete_all_assumptions_permanent,
)


CATEGORIES = [
    "Economic / Inflation",
    "Commercial",
    "Material",
    "Third-party",
]

STATUS_OPTIONS = ["Open", "Monitor", "Mitigated", "Closed"]
DRIFT_THRESHOLD = 0.03  # 3%
ASSUMPTION_ID_PATTERN = re.compile(r"^AS\d{3}$")
IMPORT_REQUIRED_HEADERS = [
    "assumption_ID",
    "Project_ID",
    "Project_Name",
    "Assumption",
    "dependencies",
    "date",
    "price_per_unit",
    "currency",
    "Denomination_of_Qty",
    "Qty",
    "Total cost",
    "Category",
    "Drift_type",
]


@dataclass
class AdjustmentResult:
    adjusted_value: float
    net_drift_pct: float
    dependency_factor_pct: float


def _seed_records() -> List[Dict]:
    """Generate initial seed records."""
    today = date.today()
    records = [
        {
            "assumption_id": "AS001",
            "title": "Annual CPI inflation",
            "category": "Economic / Inflation",
            "owner": "Finance",
            "description": "Inflation used for cost uplift in forecast.",
            "baseline_value": 0.03,
            "current_value": 0.035,
            "unit": "%",
            "internal_drift_pct": 0.002,
            "external_drift_pct": 0.015,
            "confidence_score": 78,
            "last_review_date": today.replace(day=max(1, today.day - 25)),
            "review_interval_days": 30,
            "dependencies": "",
            "status": "Monitor",
        },
        {
            "assumption_id": "AS002",
            "title": "Supplier lead time",
            "category": "Third-party",
            "owner": "Procurement",
            "description": "Average lead time from external supplier.",
            "baseline_value": 12,
            "current_value": 14,
            "unit": "weeks",
            "internal_drift_pct": 0.04,
            "external_drift_pct": 0.05,
            "confidence_score": 65,
            "last_review_date": today.replace(day=max(1, today.day - 40)),
            "review_interval_days": 21,
            "dependencies": "AS003",
            "status": "Open",
        },
        {
            "assumption_id": "AS003",
            "title": "Steel unit cost",
            "category": "Material",
            "owner": "Engineering",
            "description": "Unit cost used in fabrication cost model.",
            "baseline_value": 950,
            "current_value": 1020,
            "unit": "USD/ton",
            "internal_drift_pct": 0.01,
            "external_drift_pct": 0.08,
            "confidence_score": 72,
            "last_review_date": today.replace(day=max(1, today.day - 17)),
            "review_interval_days": 14,
            "dependencies": "AS001",
            "status": "Monitor",
        },
        {
            "assumption_id": "AS004",
            "title": "Contract margin",
            "category": "Commercial",
            "owner": "Commercial",
            "description": "Margin assumption for bid pricing.",
            "baseline_value": 0.14,
            "current_value": 0.13,
            "unit": "%",
            "internal_drift_pct": -0.02,
            "external_drift_pct": -0.005,
            "confidence_score": 84,
            "last_review_date": today.replace(day=max(1, today.day - 9)),
            "review_interval_days": 30,
            "dependencies": "AS001,AS003",
            "status": "Monitor",
        },
    ]
    return records


def _ensure_state() -> None:
    if "assumptions_df" not in st.session_state:
        init_db()
        seed_db_if_empty(_seed_records())
        st.session_state.assumptions_df = pd.DataFrame(load_assumptions())


def _parse_dependencies(dep_text: str) -> List[str]:
    if not dep_text:
        return []
    return [x.strip() for x in dep_text.split(",") if x.strip()]


def _compute_dependency_factor(
    row: pd.Series,
    assumptions_by_id: Dict[str, pd.Series],
) -> float:
    deps = _parse_dependencies(str(row.get("dependencies", "")))
    if not deps:
        return 0.0

    weighted_impact = 0.0
    total_weight = 0.0
    for dep_id in deps:
        dep = assumptions_by_id.get(dep_id)
        if dep is None:
            continue

        dep_net = float(dep["internal_drift_pct"]) + float(dep["external_drift_pct"])
        dep_conf = float(dep["confidence_score"]) / 100.0

        weighted_impact += dep_net * dep_conf
        total_weight += dep_conf

    if total_weight == 0.0:
        return 0.0

    return weighted_impact / total_weight


def _adjust_assumption(
    row: pd.Series,
    assumptions_by_id: Dict[str, pd.Series],
) -> AdjustmentResult:
    baseline = float(row["baseline_value"])
    internal_drift = float(row["internal_drift_pct"])
    external_drift = float(row["external_drift_pct"])
    confidence_weight = float(row["confidence_score"]) / 100.0

    net_drift = internal_drift + external_drift
    dependency_factor = _compute_dependency_factor(row, assumptions_by_id)

    # Confidence dampens self-drift sensitivity and dependency pull.
    drift_effective = (net_drift * confidence_weight) + (dependency_factor * 0.5)
    adjusted = baseline * (1 + drift_effective)

    return AdjustmentResult(
        adjusted_value=adjusted,
        net_drift_pct=net_drift,
        dependency_factor_pct=dependency_factor,
    )


def _days_since(d: date) -> int:
    return (date.today() - d).days


def _review_status(last_review_date: date, interval_days: int) -> str:
    age = _days_since(last_review_date)
    if age > interval_days:
        return "Overdue"
    if age >= interval_days * 0.8:
        return "Due soon"
    return "Current"


def _drift_type(internal_drift: float, external_drift: float) -> str:
    if abs(internal_drift) >= abs(external_drift):
        return "Internal-driven"
    return "External-driven"


def _confidence_band(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def _prepare_view(df: pd.DataFrame) -> pd.DataFrame:
    assumptions_by_id = {r["assumption_id"]: r for _, r in df.iterrows()}

    rows = []
    for _, row in df.iterrows():
        result = _adjust_assumption(row, assumptions_by_id)
        last_review = row["last_review_date"]
        if isinstance(last_review, str):
            last_review = datetime.strptime(last_review, "%Y-%m-%d").date()

        days_old = _days_since(last_review)
        review_state = _review_status(last_review, int(row["review_interval_days"]))

        rows.append(
            {
                **row.to_dict(),
                "net_drift_pct": result.net_drift_pct,
                "dependency_factor_pct": result.dependency_factor_pct,
                "adjusted_value": result.adjusted_value,
                "drift_type": _drift_type(
                    float(row["internal_drift_pct"]),
                    float(row["external_drift_pct"])
                ),
                "confidence_band": _confidence_band(float(row["confidence_score"])),
                "review_age_days": days_old,
                "review_status": review_state,
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(by=["review_status", "category", "assumption_id"])
    return out


def _assumption_option_label(row: pd.Series) -> str:
    assumption_id = str(row.get("assumption_id", "")).strip()
    title = str(row.get("title", "")).strip() or "Untitled"
    category = str(row.get("category", "")).strip() or "Uncategorized"
    owner = str(row.get("owner", "")).strip() or "Unknown owner"
    return f"{assumption_id} | {title} | {category} | {owner}"


def _assumption_label_map(df: pd.DataFrame) -> Dict[str, str]:
    if df.empty:
        return {}
    labels: Dict[str, str] = {}
    for _, row in df.iterrows():
        assumption_id = str(row.get("assumption_id", "")).strip()
        if assumption_id:
            labels[assumption_id] = _assumption_option_label(row)
    return labels


def _add_assumption_with_audit(row: Dict, change_reason: str) -> None:
    params = inspect.signature(add_assumption).parameters
    if "change_reason" in params:
        add_assumption(row, user="user", change_reason=change_reason)
        return

    add_assumption(row, user="user")


def _update_assumption_with_audit(
    assumption_id: str,
    updates: Dict,
    change_reason: str,
) -> None:
    params = inspect.signature(update_assumption).parameters
    if "change_reason" in params:
        update_assumption(
            assumption_id,
            updates,
            user="user",
            change_reason=change_reason,
        )
        return

    update_assumption(assumption_id, updates, user="user")


def _canonical_col(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_")


def _normalize_assumption_id(value: Any) -> str:
    return str(value).strip().upper()


def _is_valid_assumption_id(value: str) -> bool:
    return bool(ASSUMPTION_ID_PATTERN.match(value))


def _next_assumption_id(used_ids: set[str]) -> str:
    counter = 1
    while True:
        candidate = f"AS{counter:03d}"
        if candidate not in used_ids:
            return candidate
        counter += 1


def _remap_dependency_ids(dep_text: str, source_to_assigned: Dict[str, str]) -> str:
    deps = _parse_dependencies(dep_text)
    if not deps:
        return ""

    remapped: List[str] = []
    for dep in deps:
        dep_norm = _normalize_assumption_id(dep)
        if dep_norm in source_to_assigned:
            remapped.append(source_to_assigned[dep_norm])
        elif _is_valid_assumption_id(dep_norm):
            remapped.append(dep_norm)
        else:
            remapped.append(dep)
    return ",".join(remapped)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt or txt.lower() in {"nan", "none"}:
        return None
    txt = txt.replace(",", "")
    try:
        return float(txt)
    except ValueError:
        return None


def _safe_date(value: Any) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    txt = str(value).strip()
    if not txt:
        return date.today()

    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue

    parsed = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return date.today()
    return parsed.date()


def _normalize_import_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {col: _canonical_col(col) for col in df.columns}
    return df.rename(columns=rename_map)


def _validate_import_headers(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    required = [_canonical_col(h) for h in IMPORT_REQUIRED_HEADERS]
    present = set(df.columns.tolist())
    missing = [h for h in required if h not in present]
    return (len(missing) == 0, missing)


def _map_import_row_to_assumption(row: pd.Series) -> Dict[str, Any]:
    assumption_id = str(row.get("assumption_id", "")).strip()
    assumption_text = str(row.get("assumption", "")).strip()
    project_id = str(row.get("project_id", "")).strip()
    project_name = str(row.get("project_name", "")).strip()
    category = str(row.get("category", "Commercial")).strip() or "Commercial"
    dependencies = str(row.get("dependencies", "")).strip()

    price_per_unit = _safe_float(row.get("price_per_unit"))
    total_cost = _safe_float(row.get("total_cost"))
    qty = _safe_float(row.get("qty"))

    currency = str(row.get("currency", "")).strip()
    denomination = str(row.get("denomination_of_qty", "")).strip()
    drift_type_raw = str(row.get("drift_type", "")).strip().lower()

    baseline_value = price_per_unit if price_per_unit is not None else (total_cost if total_cost is not None else 0.0)
    current_value = total_cost if total_cost is not None else baseline_value

    unit_parts = [part for part in [currency, denomination] if part]
    unit = " / ".join(unit_parts)

    drift_from_price = 0.0
    if price_per_unit is not None and "percentage" in denomination.lower():
        drift_from_price = price_per_unit / 100.0

    internal_drift = drift_from_price if drift_type_raw.startswith("internal") else 0.0
    external_drift = drift_from_price if drift_type_raw.startswith("external") else 0.0

    title = assumption_text[:80] if assumption_text else f"Imported assumption {assumption_id}"
    description = assumption_text
    if project_id or project_name:
        description = (
            f"{assumption_text}\\n\\n"
            f"Imported from Project_ID={project_id}, Project_Name={project_name}."
        ).strip()
    if qty is not None:
        description = f"{description}\\nQty: {qty}".strip()

    return {
        "assumption_id": assumption_id,
        "title": title,
        "category": category,
        "owner": "Imported",
        "description": description,
        "baseline_value": baseline_value,
        "current_value": current_value,
        "unit": unit,
        "internal_drift_pct": internal_drift,
        "external_drift_pct": external_drift,
        "confidence_score": 70,
        "last_review_date": _safe_date(row.get("date")),
        "review_interval_days": 30,
        "dependencies": dependencies,
        "status": "Open",
    }


def _render_xlsx_import() -> None:
    st.subheader("Import XLSX")
    st.caption("Upload assumptions in the provided template headers for bulk create/update.")

    uploaded = st.file_uploader("Upload .xlsx", type=["xlsx"], key="assumption_xlsx_upload")
    if uploaded is None:
        return

    try:
        raw_df = pd.read_excel(uploaded)
    except Exception as exc:
        st.error(f"Could not read workbook: {exc}")
        return

    normalized_df = _normalize_import_columns(raw_df)
    ok, missing = _validate_import_headers(normalized_df)
    if not ok:
        st.error(
            "Missing required headers: " + ", ".join(missing)
        )
        return

    st.write("Preview")
    st.dataframe(raw_df.head(10), use_container_width=True, hide_index=True)

    existing = pd.DataFrame(load_assumptions())
    existing_ids = (
        set(existing["assumption_id"].astype(str).map(_normalize_assumption_id).tolist())
        if not existing.empty
        else set()
    )

    assignment_rows: List[Dict[str, Any]] = []
    used_new_ids: set[str] = set()
    used_for_generation = set(existing_ids)

    for idx, row in normalized_df.iterrows():
        source_id = _normalize_assumption_id(row.get("assumption_id", ""))
        suggestion = source_id
        needs_assignment = False

        if not _is_valid_assumption_id(source_id) or source_id in used_new_ids:
            suggestion = _next_assumption_id(used_for_generation | used_new_ids)
            needs_assignment = True

        used_new_ids.add(suggestion)

        assignment_rows.append(
            {
                "row_number": int(idx + 2),
                "source_assumption_id": source_id,
                "assumption": str(row.get("assumption", ""))[:80],
                "assigned_assumption_id": suggestion,
                "needs_assignment": needs_assignment,
            }
        )

    assignment_df = pd.DataFrame(assignment_rows)
    invalid_count = int(assignment_df["needs_assignment"].sum()) if not assignment_df.empty else 0

    if invalid_count > 0:
        st.warning(
            f"{invalid_count} row(s) contain non-conforming or duplicate IDs. "
            "Please confirm or edit assigned IDs (format ASXXX)."
        )

    edited_assignment_df = st.data_editor(
        assignment_df,
        use_container_width=True,
        hide_index=True,
        disabled=["row_number", "source_assumption_id", "assumption", "needs_assignment"],
        column_config={
            "row_number": st.column_config.NumberColumn("Row"),
            "source_assumption_id": st.column_config.TextColumn("Source ID"),
            "assigned_assumption_id": st.column_config.TextColumn("Assigned ID (ASXXX)"),
            "needs_assignment": st.column_config.CheckboxColumn("Needed assignment"),
        },
        key="import_id_assignment_editor",
    )

    import_reason = st.text_input(
        "Import reason (for audit log)",
        value="Bulk XLSX import",
        key="xlsx_import_reason",
    )

    if st.button("Import rows", key="xlsx_import_btn"):
        assigned_ids = edited_assignment_df["assigned_assumption_id"].astype(str).map(_normalize_assumption_id).tolist()
        invalid_assigned = [x for x in assigned_ids if not _is_valid_assumption_id(x)]
        duplicate_assigned = len(set(assigned_ids)) != len(assigned_ids)

        if invalid_assigned:
            st.error("All assigned IDs must match format ASXXX (e.g., AS001).")
            return
        if duplicate_assigned:
            st.error("Assigned IDs must be unique within the uploaded file.")
            return

        row_to_assigned = {
            int(r["row_number"]): _normalize_assumption_id(r["assigned_assumption_id"])
            for _, r in edited_assignment_df.iterrows()
        }

        source_to_assigned: Dict[str, str] = {}
        for _, r in edited_assignment_df.iterrows():
            src = _normalize_assumption_id(r["source_assumption_id"])
            if src and src not in source_to_assigned:
                source_to_assigned[src] = _normalize_assumption_id(r["assigned_assumption_id"])

        created = 0
        updated = 0
        skipped = 0
        errors: List[str] = []

        for idx, row in normalized_df.iterrows():
            mapped = _map_import_row_to_assumption(row)
            assumption_id = row_to_assigned.get(int(idx + 2), "")
            if not assumption_id:
                skipped += 1
                errors.append(f"Row {idx + 2}: empty assumption_ID")
                continue

            mapped["assumption_id"] = assumption_id
            mapped["dependencies"] = _remap_dependency_ids(mapped.get("dependencies", ""), source_to_assigned)

            try:
                if assumption_id in existing_ids:
                    updates = {
                        "title": mapped["title"],
                        "category": mapped["category"],
                        "owner": mapped["owner"],
                        "description": mapped["description"],
                        "baseline_value": mapped["baseline_value"],
                        "current_value": mapped["current_value"],
                        "unit": mapped["unit"],
                        "internal_drift_pct": mapped["internal_drift_pct"],
                        "external_drift_pct": mapped["external_drift_pct"],
                        "last_review_date": mapped["last_review_date"],
                        "dependencies": mapped["dependencies"],
                        "status": mapped["status"],
                    }
                    _update_assumption_with_audit(
                        assumption_id,
                        updates,
                        change_reason=import_reason.strip() or "Bulk XLSX import",
                    )
                    updated += 1
                else:
                    _add_assumption_with_audit(
                        mapped,
                        change_reason=import_reason.strip() or "Bulk XLSX import",
                    )
                    created += 1
                    existing_ids.add(assumption_id)
            except Exception as exc:
                skipped += 1
                errors.append(f"Row {idx + 2} ({assumption_id}): {exc}")

        st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
        st.success(f"Import complete. Created: {created}, Updated: {updated}, Skipped: {skipped}.")
        if errors:
            st.warning("Some rows were skipped. See details below.")
            st.dataframe(pd.DataFrame({"errors": errors}), use_container_width=True, hide_index=True)


def _add_assumption_form() -> None:
    st.subheader("Add Assumption")
    with st.form("add_assumption"):
        c1, c2, c3 = st.columns(3)
        assumption_id = c1.text_input("Assumption ID", placeholder="AS005")
        title = c2.text_input("Assumption (Title)")
        category = c3.selectbox("Category", options=CATEGORIES)

        owner = st.text_input("Owner")
        description = st.text_area("Description")

        st.caption("Core financial and drift fields")

        c4, c5, c6 = st.columns(3)
        baseline_value = c4.number_input("Baseline value", value=0.0, step=0.01)
        current_value = c5.number_input("Current value", value=0.0, step=0.01)
        unit = c6.text_input("Unit (e.g. %, USD, weeks)", value="")

        c7, c8, c9 = st.columns(3)
        internal_drift_pct = c7.number_input("Internal drift %", value=0.0, step=0.1)
        external_drift_pct = c8.number_input("External drift %", value=0.0, step=0.1)
        confidence_score = c9.slider("Confidence score", min_value=0, max_value=100, value=70)

        c10, c11, c12 = st.columns(3)
        last_review_date = c10.date_input("Last review date", value=date.today())
        review_interval_days = c11.number_input("Review interval (days)", min_value=1, value=30)
        status = c12.selectbox("Status", STATUS_OPTIONS)

        dependencies = st.text_input(
            "Dependencies (comma-separated assumption IDs)",
            placeholder="AS001,AS003",
        )

        with st.expander("Optional import-style fields (Project / Qty / Currency)"):
            p1, p2 = st.columns(2)
            project_id = p1.text_input("Project ID", value="")
            project_name = p2.text_input("Project Name", value="")

            p3, p4, p5 = st.columns(3)
            price_per_unit = p3.text_input("Price per unit", value="")
            total_cost = p4.text_input("Total cost", value="")
            qty = p5.text_input("Qty", value="")

            p6, p7, p8 = st.columns(3)
            currency = p6.text_input("Currency", value="")
            denomination_of_qty = p7.text_input("Denomination of Qty", value="")
            drift_type = p8.selectbox("Drift type", ["", "Internal", "External"], index=0)

            st.caption(
                "If provided, these values are mapped into the stored assumption fields "
                "(description/unit/baseline/current/drift) in the same style as XLSX import."
            )

        st.caption("System-managed fields: created_at and updated_at are set automatically.")

        change_reason = st.text_input("Change reason / notes (for audit log)")

        submitted = st.form_submit_button("Add to register")
        if submitted:
            normalized_assumption_id = _normalize_assumption_id(assumption_id)

            if not normalized_assumption_id or not title.strip() or not owner.strip():
                st.error("Assumption ID, Title, and Owner are required.")
                return

            if not _is_valid_assumption_id(normalized_assumption_id):
                st.error("Assumption ID must use format ASXXX (e.g., AS001).")
                return

            # Check if assumption already exists
            existing = pd.DataFrame(load_assumptions())
            existing_ids = (
                set(existing["assumption_id"].astype(str).map(_normalize_assumption_id).tolist())
                if not existing.empty
                else set()
            )
            if normalized_assumption_id in existing_ids:
                st.error("Assumption ID already exists.")
                return

            row = {
                "assumption_id": normalized_assumption_id,
                "title": title.strip(),
                "category": category,
                "owner": owner.strip(),
                "description": description.strip(),
                "baseline_value": baseline_value,
                "current_value": current_value,
                "unit": unit.strip(),
                "internal_drift_pct": internal_drift_pct / 100.0,
                "external_drift_pct": external_drift_pct / 100.0,
                "confidence_score": int(confidence_score),
                "last_review_date": last_review_date,
                "review_interval_days": int(review_interval_days),
                "dependencies": dependencies.strip(),
                "status": status,
            }

            # Optional import-style mapping to align manual create with XLSX import behavior.
            price_per_unit_val = _safe_float(price_per_unit)
            total_cost_val = _safe_float(total_cost)
            qty_val = _safe_float(qty)

            if project_id.strip() or project_name.strip() or qty_val is not None:
                desc = row["description"]
                if project_id.strip() or project_name.strip():
                    project_line = (
                        f"Imported from Project_ID={project_id.strip()}, "
                        f"Project_Name={project_name.strip()}."
                    )
                    desc = f"{desc}\\n\\n{project_line}".strip()
                if qty_val is not None:
                    desc = f"{desc}\\nQty: {qty_val}".strip()
                row["description"] = desc

            if price_per_unit_val is not None and row["baseline_value"] == 0.0:
                row["baseline_value"] = price_per_unit_val
            if total_cost_val is not None and row["current_value"] == 0.0:
                row["current_value"] = total_cost_val

            if not row["unit"].strip():
                unit_parts = [x.strip() for x in [currency, denomination_of_qty] if x.strip()]
                if unit_parts:
                    row["unit"] = " / ".join(unit_parts)

            if (
                price_per_unit_val is not None
                and denomination_of_qty.strip().lower() == "percentage"
                and row["internal_drift_pct"] == 0.0
                and row["external_drift_pct"] == 0.0
            ):
                inferred_drift = price_per_unit_val / 100.0
                if drift_type == "Internal":
                    row["internal_drift_pct"] = inferred_drift
                elif drift_type == "External":
                    row["external_drift_pct"] = inferred_drift

            _add_assumption_with_audit(
                row,
                change_reason.strip() if change_reason.strip() else "",
            )
            st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
            st.success("Assumption added and logged to audit trail.")
            st.rerun()


def _render_dashboard(df_view: pd.DataFrame) -> None:
    st.subheader("Portfolio Signals")

    overdue_count = int((df_view["review_status"] == "Overdue").sum())
    external_driven = int((df_view["drift_type"] == "External-driven").sum())
    avg_conf = float(df_view["confidence_score"].mean()) if not df_view.empty else 0.0
    avg_net_drift = float(df_view["net_drift_pct"].mean()) if not df_view.empty else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Assumptions", len(df_view))
    m2.metric("Overdue reviews", overdue_count)
    m3.metric("External-driven items", external_driven)
    m4.metric("Avg confidence", f"{avg_conf:.1f}")

    st.caption(f"Average net drift: {avg_net_drift:.2%}")

    st.subheader("Category Drift")
    category_view = (
        df_view.groupby("category", as_index=False)[["internal_drift_pct", "external_drift_pct", "net_drift_pct"]]
        .mean()
        .sort_values("net_drift_pct", ascending=False)
    )
    st.bar_chart(category_view.set_index("category"))

    st.subheader("Assumption Relevance Timeline")
    if df_view.empty:
        st.info("No assumptions available for timeline view.")
        return

    timeline_df = df_view.copy()
    timeline_df["window_start"] = pd.to_datetime(timeline_df["last_review_date"])
    timeline_df["window_end"] = timeline_df["window_start"] + pd.to_timedelta(
        timeline_df["review_interval_days"].astype(int),
        unit="D",
    )
    timeline_df["today"] = pd.Timestamp(date.today())
    timeline_df["assumption_label"] = timeline_df.apply(
        lambda r: f"{r['assumption_id']} | {str(r['title'])[:50]}",
        axis=1,
    )

    timeline_df = timeline_df.sort_values(["window_end", "assumption_id"], ascending=[True, True])

    timeline_chart = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": timeline_df.to_dict(orient="records")},
        "height": min(600, max(180, int(28 * len(timeline_df)))),
        "layer": [
            {
                "mark": {"type": "bar", "cornerRadius": 3, "height": 16},
                "encoding": {
                    "y": {
                        "field": "assumption_label",
                        "type": "ordinal",
                        "sort": None,
                        "title": "Assumption",
                    },
                    "x": {
                        "field": "window_start",
                        "type": "temporal",
                        "title": "Date",
                    },
                    "x2": {"field": "window_end"},
                    "color": {
                        "field": "review_status",
                        "type": "nominal",
                        "title": "Review status",
                        "scale": {
                            "domain": ["Current", "Due soon", "Overdue"],
                            "range": ["#2E7D32", "#F9A825", "#C62828"],
                        },
                    },
                    "tooltip": [
                        {"field": "assumption_id", "type": "nominal", "title": "Assumption ID"},
                        {"field": "title", "type": "nominal", "title": "Title"},
                        {"field": "category", "type": "nominal", "title": "Category"},
                        {"field": "window_start", "type": "temporal", "title": "Window start"},
                        {"field": "window_end", "type": "temporal", "title": "Window end"},
                        {"field": "review_status", "type": "nominal", "title": "Review status"},
                    ],
                },
            },
            {
                "mark": {"type": "rule", "strokeDash": [6, 4], "color": "#1E88E5", "size": 2},
                "encoding": {
                    "x": {"field": "today", "type": "temporal"},
                },
            },
        ],
    }

    st.vega_lite_chart(timeline_df, timeline_chart, use_container_width=True)
    st.caption("Bars show each assumption's relevance window from last review date to review due date. The blue dashed line marks today.")


def _render_register(df_view: pd.DataFrame) -> None:
    st.subheader("Assumption Register")

    display = df_view.copy()
    for col in ["internal_drift_pct", "external_drift_pct", "net_drift_pct", "dependency_factor_pct"]:
        if col in display.columns:
            display[col] = (display[col] * 100.0).round(2)

    display["adjusted_value"] = display["adjusted_value"].round(4)

    columns = [
        "assumption_id",
        "title",
        "category",
        "owner",
        "status",
        "confidence_score",
        "confidence_band",
        "drift_type",
        "internal_drift_pct",
        "external_drift_pct",
        "net_drift_pct",
        "dependency_factor_pct",
        "baseline_value",
        "current_value",
        "adjusted_value",
        "unit",
        "dependencies",
        "review_age_days",
        "review_status",
        "last_review_date",
        "review_interval_days",
    ]

    available_cols = [col for col in columns if col in display.columns]

    st.dataframe(
        display[available_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "internal_drift_pct": st.column_config.NumberColumn("Internal drift (%)"),
            "external_drift_pct": st.column_config.NumberColumn("External drift (%)"),
            "net_drift_pct": st.column_config.NumberColumn("Net drift (%)"),
            "dependency_factor_pct": st.column_config.NumberColumn("Dependency factor (%)"),
            "review_age_days": st.column_config.NumberColumn("Review age (days)"),
            "confidence_score": st.column_config.ProgressColumn(
                "Confidence",
                min_value=0,
                max_value=100,
            ),
        },
    )

    export_df = df_view.copy()
    export_df["last_review_date"] = export_df["last_review_date"].astype(str)
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📊 Export register as CSV",
        data=csv,
        file_name="assumptions_register.csv",
        mime="text/csv",
    )


def _render_audit_history() -> None:
    st.subheader("Audit History")

    filter_col1, filter_col2 = st.columns(2)
    assumptions_df = st.session_state.get("assumptions_df", pd.DataFrame())
    id_to_label = _assumption_label_map(assumptions_df)
    assumption_options = [""] + sorted(id_to_label.keys())

    with filter_col1:
        assumption_id_filter = st.selectbox(
            "Filter by assumption",
            options=assumption_options,
            format_func=lambda x: "All assumptions" if x == "" else id_to_label.get(x, x),
        )

    with filter_col2:
        action_filter = st.multiselect(
            "Filter by action",
            options=["CREATE", "UPDATE", "DELETE"],
            default=["CREATE", "UPDATE", "DELETE"],
        )

    if assumption_id_filter.strip():
        audit_data = get_audit_history(assumption_id_filter.strip())
    else:
        audit_data = get_audit_history()

    # Filter by action
    audit_data = [a for a in audit_data if a["action"] in action_filter]
    
    if not audit_data:
        st.info("No audit records found.")
        return
    
    audit_df = pd.DataFrame(audit_data)
    audit_df["timestamp"] = pd.to_datetime(audit_df["timestamp"])
    audit_df = audit_df.sort_values("timestamp", ascending=False)
    
    # Format for display
    display_audit = audit_df.copy()
    display_audit = display_audit[[
        "timestamp",
        "assumption_id",
        "action",
        "field_name",
        "old_value",
        "new_value",
        "user",
        "change_reason",
    ]]
    
    st.dataframe(
        display_audit,
        use_container_width=True,
        hide_index=True,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Timestamp", format="YYYY-MM-DD HH:mm:ss"),
        },
    )
    
    # Export audit log
    csv = audit_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Export audit log as CSV",
        data=csv,
        file_name="audit_log.csv",
        mime="text/csv",
    )


def _render_danger_zone() -> None:
    st.header("Danger Zone")
    st.warning("These actions are destructive and cannot be undone.")

    assumptions_df = st.session_state.get("assumptions_df", pd.DataFrame())

    st.subheader("Delete Individual Assumption")
    if assumptions_df.empty:
        st.info("No assumptions available to delete.")
    else:
        id_to_label = _assumption_label_map(assumptions_df)
        ids = sorted(id_to_label.keys())

        selected_id = st.selectbox(
            "Choose assumption to delete",
            options=ids,
            format_func=lambda x: id_to_label.get(x, x),
            key="danger_select_assumption",
        )
        st.caption("Type the selected assumption ID to confirm deletion.")
        confirm_single = st.text_input(
            "Confirm single delete",
            placeholder=f"Type {selected_id}",
            key="danger_confirm_single",
        )

        if st.button("Delete selected assumption", type="primary", key="danger_delete_single"):
            if confirm_single.strip().upper() != selected_id:
                st.error(f"Confirmation mismatch. Type exactly {selected_id} to proceed.")
            else:
                delete_assumption_permanent(selected_id)
                st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
                st.success(f"Deleted assumption {selected_id}.")
                st.rerun()

    st.divider()
    st.subheader("Delete All Assumptions")
    st.caption("This removes all assumptions and their audit history.")
    confirm_all = st.text_input(
        "Type DELETE ALL to confirm",
        placeholder="DELETE ALL",
        key="danger_confirm_all",
    )
    if st.button("Delete all assumptions", type="primary", key="danger_delete_all"):
        if confirm_all.strip().upper() != "DELETE ALL":
            st.error("Confirmation mismatch. Type DELETE ALL to proceed.")
        else:
            delete_all_assumptions_permanent()
            st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
            st.success("All assumptions deleted.")
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Clearly We Assumed - The Assumptionisator", layout="wide")
    st.title("The Assumptionisator")
    st.caption(
        "Clearly We Assumed ProjectHack27 team submission - Track assumption drift, dependencies, confidence, and review currency with persistent storage and audit trail."
    )

    _ensure_state()

    with st.sidebar:
        st.header("Filters")
        df_raw = st.session_state.assumptions_df.copy()

        category_filter = st.multiselect(
            "Category",
            options=sorted(df_raw["category"].unique().tolist()),
            default=sorted(df_raw["category"].unique().tolist()),
        )
        status_filter = st.multiselect(
            "Status",
            options=sorted(df_raw["status"].unique().tolist()),
            default=sorted(df_raw["status"].unique().tolist()),
        )
        max_review_age = st.slider("Max review age (days)", min_value=0, max_value=180, value=180)
        min_confidence = st.slider("Minimum confidence", min_value=0, max_value=100, value=0)

        st.divider()
        if st.button("🔄 Reset & reload from DB"):
            st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
            st.rerun()
        
        if st.button("🗑️ Delete all data & reset"):
            if st.session_state.get("confirm_delete"):
                reset_and_seed_data(_seed_records())
                st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
                st.session_state.confirm_delete = False
                st.success("All data cleared and reset to seed data.")
                st.rerun()
            else:
                st.session_state.confirm_delete = True
                st.warning("Click again to confirm delete.")

    df = st.session_state.assumptions_df.copy()

    if category_filter:
        df = df[df["category"].isin(category_filter)]
    if status_filter:
        df = df[df["status"].isin(status_filter)]

    df_view = _prepare_view(df)
    df_view = df_view[
        (df_view["review_age_days"] <= max_review_age)
        & (df_view["confidence_score"] >= min_confidence)
    ]

    t1, t2, t3, t4, t5 = st.tabs(["Dashboard", "Register", "Add/Update", "Audit History", "Danger Zone"])

    with t1:
        _render_dashboard(df_view)

    with t2:
        _render_register(df_view)

    with t3:
        _render_xlsx_import()
        st.divider()
        _add_assumption_form()

        st.subheader("Update confidence and review date")
        if not st.session_state.assumptions_df.empty:
            assumptions_df = st.session_state.assumptions_df.copy()
            ids = assumptions_df["assumption_id"].astype(str).tolist()
            id_to_label = _assumption_label_map(assumptions_df)
            selected_id = st.selectbox(
                "Select assumption",
                options=ids,
                format_func=lambda x: id_to_label.get(x, x),
            )

            selected_row = assumptions_df[assumptions_df["assumption_id"] == selected_id].iloc[0]
            st.caption(
                f"Category: {selected_row['category']} | Owner: {selected_row['owner']} | "
                f"Status: {selected_row['status']} | Last review: {selected_row['last_review_date']}"
            )
            st.text_area(
                "Assumption details",
                value=str(selected_row.get("description", "")),
                height=100,
                disabled=True,
            )

            with st.form("quick_update"):
                new_conf = st.slider(
                    "Confidence score",
                    min_value=0,
                    max_value=100,
                    value=int(selected_row["confidence_score"]),
                )
                new_review_date = st.date_input(
                    "Last review date",
                    value=selected_row["last_review_date"],
                )
                new_status = st.selectbox(
                    "Status",
                    options=STATUS_OPTIONS,
                    index=STATUS_OPTIONS.index(selected_row["status"]),
                )
                
                update_reason = st.text_input("Update reason (for audit log)")

                submitted = st.form_submit_button("Apply update")
                if submitted:
                    updates = {
                        "confidence_score": int(new_conf),
                        "last_review_date": new_review_date,
                        "status": new_status,
                    }
                    _update_assumption_with_audit(
                        selected_id,
                        updates,
                        change_reason=update_reason.strip() if update_reason.strip() else "Routine review",
                    )
                    st.session_state.assumptions_df = pd.DataFrame(load_assumptions())
                    st.success("Assumption updated and logged to audit trail.")
                    st.rerun()

    with t4:
        _render_audit_history()

    with t5:
        _render_danger_zone()


if __name__ == "__main__":
    main()
