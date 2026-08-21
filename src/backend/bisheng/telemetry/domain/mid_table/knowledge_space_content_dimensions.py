"""Shared dimension rules for knowledge-space content statistics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

ORG_LEVEL_FIELD_NAMES = {
    "company": "company_name",
    "dept": "department_name",
    "office": "office_name",
    "squad": "squad_name",
}

ORGANIZATION_NAME_FIELDS = (
    "company_name",
    "department_name",
    "office_name",
    "squad_name",
)

CONTENT_DIMENSION_FIELDS = (
    "space_id",
    "space_name",
    "space_level",
    "space_level_name",
    "file_id",
    "file_name",
    "file_type",
    "file_category_code",
    "file_category_name",
    "file_subcategory_code",
    "file_subcategory_name",
    "business_domain_code",
    "business_domain_name",
    "uploader_user_id",
    "uploader_user_name",
    "uploader_company_name",
    "uploader_department_name",
    "uploader_office_name",
    "uploader_squad_name",
    "belonging_company_name",
    "belonging_department_name",
    "belonging_office_name",
    "belonging_squad_name",
)


class OrganizationNameSnapshot(BaseModel):
    company_name: str | None = None
    department_name: str | None = None
    office_name: str | None = None
    squad_name: str | None = None

    def prefixed(self, prefix: str) -> dict[str, str | None]:
        return {f"{prefix}_{field}": getattr(self, field) for field in ORGANIZATION_NAME_FIELDS}


def _path_ids(path: str | None) -> list[int]:
    result: list[int] = []
    for value in str(path or "").strip("/").split("/"):
        if not value:
            continue
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def resolve_organization_names(
    start_department: Any | None,
    departments_by_id: Mapping[int, Any],
) -> OrganizationNameSnapshot:
    """Resolve labeled ancestors; the first squad on the root path wins."""
    if start_department is None:
        return OrganizationNameSnapshot()

    ordered_ids = _path_ids(getattr(start_department, "path", None))
    start_id = getattr(start_department, "id", None)
    if start_id is not None and int(start_id) not in ordered_ids:
        ordered_ids.append(int(start_id))

    values: dict[str, str] = {}
    for department_id in ordered_ids:
        department = departments_by_id.get(department_id)
        if department is None or getattr(department, "status", "active") != "active":
            continue
        field = ORG_LEVEL_FIELD_NAMES.get(str(getattr(department, "org_level", "") or ""))
        if field and field not in values:
            name = str(getattr(department, "name", "") or "").strip()
            if name:
                values[field] = name
    return OrganizationNameSnapshot(**values)


def build_daily_document_id(
    *,
    record_type: str,
    file_id: int,
    local_date: str,
    dimensions: Mapping[str, Any],
) -> str:
    payload = {field: dimensions.get(field) for field in CONTENT_DIMENSION_FIELDS}
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"{record_type}:{int(file_id)}:{local_date}:{digest}"
