"""Person primary-department names for dashboard filters.

The three fields use the same identifiers as knowledge-space file belonging.
Values come from the row's person, not from a file.
"""

from collections.abc import Mapping
from typing import Any

from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import resolve_organization_names

BELONGING_ORGANIZATION_FIELDS = (
    "belonging_company_name",
    "belonging_department_name",
    "belonging_office_name",
)

BELONGING_GROUP_DATASETS = frozenset(
    {
        "mid_user_increment",
        "mid_user_daily_participation",
        "mid_active_user",
        "mid_realtime_qa_question_fact",
    }
)

ASKER_TO_BELONGING = (
    ("asker_company_name", "belonging_company_name"),
    ("asker_department_name", "belonging_department_name"),
    ("asker_office_name", "belonging_office_name"),
)

BELONGING_NAME_MAPPING = {
    field: {
        "type": "keyword",
        "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
    }
    for field in BELONGING_ORGANIZATION_FIELDS
}


def organization_department_ids(department: Any | None) -> list[int]:
    """Department ids on the materialized path, including the start node."""
    if department is None:
        return []
    ordered: list[int] = []
    for value in str(getattr(department, "path", None) or "").strip("/").split("/"):
        if not value.isdigit():
            continue
        department_id = int(value)
        if department_id not in ordered:
            ordered.append(department_id)
    start_id = getattr(department, "id", None)
    if start_id is not None and int(start_id) not in ordered:
        ordered.append(int(start_id))
    return ordered


def department_is_usable(department: Any | None, tenant_id: int) -> bool:
    """Same usability rule as file belonging: active, not deleted, same tenant."""
    if department is None:
        return False
    department_tenant_id = getattr(department, "tenant_id", None)
    if department_tenant_id is None or int(department_tenant_id) != int(tenant_id):
        return False
    if str(getattr(department, "status", "") or "") != "active":
        return False
    if getattr(department, "is_deleted", 0):
        return False
    return True


def belonging_names(
    department: Any | None,
    departments_by_id: Mapping[int, Any],
    tenant_id: int,
) -> dict[str, str]:
    """Full names only. Empty levels are omitted, never stored as blanks."""
    if not department_is_usable(department, tenant_id):
        return {}
    by_id = dict(departments_by_id)
    start_id = getattr(department, "id", None)
    if start_id is not None:
        by_id.setdefault(int(start_id), department)
    snapshot = resolve_organization_names(department, by_id)
    prefixed = snapshot.prefixed("belonging")
    return {field: prefixed[field] for field in BELONGING_ORGANIZATION_FIELDS if prefixed.get(field)}


def qa_belonging_names(
    source: Mapping[str, Any],
    department: Any | None,
    departments_by_id: Mapping[int, Any],
) -> dict[str, str]:
    """Copy asker names already on the row. Expand the stored id only when all three are empty."""
    copied = {}
    for source_field, target_field in ASKER_TO_BELONGING:
        value = source.get(source_field)
        if isinstance(value, str) and value.strip():
            copied[target_field] = value.strip()
    if copied:
        return copied
    return belonging_names(department, departments_by_id, int(source.get("tenant_id") or 1))


def without_empty_belonging(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    for field in BELONGING_ORGANIZATION_FIELDS:
        if result.get(field) in (None, ""):
            result.pop(field, None)
    return result


def apply_belonging_names(source: Mapping[str, Any], names: Mapping[str, str]) -> dict[str, Any]:
    """Replace the three fields on a copy. Other fields stay. Empty names delete the field."""
    result = dict(source)
    for field in BELONGING_ORGANIZATION_FIELDS:
        value = names.get(field)
        if value:
            result[field] = value
        else:
            result.pop(field, None)
    return result


def merge_belonging_backfill(current: dict[str, Any], desired: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a precomputed name patch onto the fresh document. Do not create rows."""
    if not current:
        return dict(current)
    return apply_belonging_names(current, desired.get("names") or {})


def belonging_terms_missing(dataset_code: str, field: str) -> dict[str, str] | None:
    """Group missing values into an empty key for user and QA charts only."""
    if dataset_code in BELONGING_GROUP_DATASETS and field in BELONGING_ORGANIZATION_FIELDS:
        return {"missing": ""}
    return None
