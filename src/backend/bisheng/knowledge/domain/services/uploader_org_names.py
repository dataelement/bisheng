"""把文件登记的组织拆成公司、部门、科室名称.

与内容统计同一套规则: 沿 department.path 找第一个仍有效的 company / dept / office.
组织不存在时三个名称都为空.
"""

from __future__ import annotations

from typing import Any

from bisheng.points.domain.constants.org_levels import org_level_for_path

_LEVEL_FIELDS = {
    "company": "company_name",
    "dept": "department_name",
    "office": "office_name",
}
EMPTY_UPLOADER_ORG = {
    "company_name": "",
    "department_name": "",
    "office_name": "",
}


def path_ids(path: str | None) -> list[int]:
    result: list[int] = []
    for value in str(path or "").strip("/").split("/"):
        if not value:
            continue
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def resolve_uploader_org_names(
    start: Any | None,
    departments_by_id: dict[int, Any],
    company_path: str | None = None,
) -> dict[str, str]:
    names = dict(EMPTY_UPLOADER_ORG)
    if start is None:
        return names
    ordered = path_ids(getattr(start, "path", None))
    start_id = getattr(start, "id", None)
    if start_id is not None and int(start_id) not in ordered:
        ordered.append(int(start_id))
    for department_id in ordered:
        department = departments_by_id.get(department_id)
        if department is None or str(getattr(department, "status", "active") or "") != "active":
            continue
        level = str(getattr(department, "org_level", "") or "")
        if not level and company_path:
            level = org_level_for_path(company_path, getattr(department, "path", None)) or ""
        field = _LEVEL_FIELDS.get(level)
        if field is None or names[field]:
            continue
        name = str(getattr(department, "name", "") or "").strip()
        if name:
            names[field] = name
    return names
