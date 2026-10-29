"""用户当前主部门上的公司、部门、科室.

审计列表不把这三个名称写入 audit_log 或 message_session.
展示只解析当前页的用户. 筛选先在 department / user_department 上收成用户 ID,
再交给 audit_log.operator_id 和 message_session.user_id 上已有的索引.
"""

from __future__ import annotations

from typing import Any

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.knowledge.domain.services.uploader_org_names import (
    path_ids,
    resolve_uploader_org_names,
)
from bisheng.points.domain.constants.org_levels import org_level_for_path

EMPTY_USER_ORG = {
    "department_name": "",
    "company_name": "",
    "office_name": "",
}

_OPTION_KEYS = {
    "dept": "departments",
    "company": "companies",
    "office": "offices",
}


def _active(node: Any) -> bool:
    return str(getattr(node, "status", "") or "") == "active"


def _company_path(node: Any, departments_by_id: dict[int, Any]) -> str | None:
    for department_id in path_ids(getattr(node, "path", None)):
        ancestor = departments_by_id.get(department_id)
        if ancestor is None or not _active(ancestor):
            continue
        if str(getattr(ancestor, "org_level", "") or "") == "company":
            path = str(getattr(ancestor, "path", "") or "")
            if path:
                return path
    return None


def resolved_org_level(node: Any, departments_by_id: dict[int, Any]) -> str:
    explicit = str(getattr(node, "org_level", "") or "")
    if explicit:
        return explicit
    company_path = _company_path(node, departments_by_id)
    if not company_path:
        return ""
    return org_level_for_path(company_path, getattr(node, "path", None)) or ""


def org_names_from_department(start: Any | None, departments_by_id: dict[int, Any]) -> dict[str, str]:
    if start is None:
        return dict(EMPTY_USER_ORG)
    names = resolve_uploader_org_names(start, departments_by_id, _company_path(start, departments_by_id))
    return {
        "department_name": names["department_name"],
        "company_name": names["company_name"],
        "office_name": names["office_name"],
    }


def _clean_name(value: str | None) -> str:
    return str(value or "").strip()


async def org_names_for_users(user_ids: list[int]) -> dict[int, dict[str, str]]:
    """当前页用户的三个名称. 每人只取 department_id 最小的一条主部门."""
    normalized = sorted({int(user_id) for user_id in user_ids if user_id})
    if not normalized:
        return {}
    memberships = await UserDepartmentDao.aget_by_user_ids(normalized)
    primary_department_id: dict[int, int] = {}
    for row in memberships:
        if int(getattr(row, "is_primary", 0) or 0) != 1:
            continue
        user_id = int(row.user_id)
        department_id = int(row.department_id)
        current = primary_department_id.get(user_id)
        if current is None or department_id < current:
            primary_department_id[user_id] = department_id
    if not primary_department_id:
        return {}
    departments = await DepartmentDao.aget_by_ids(sorted(set(primary_department_id.values())))
    by_id = {int(row.id): row for row in departments if row.id is not None}
    missing = {department_id for row in departments for department_id in path_ids(row.path)} - set(by_id)
    if missing:
        ancestors = await DepartmentDao.aget_by_ids(sorted(missing))
        for row in ancestors:
            if row.id is not None:
                by_id[int(row.id)] = row
    return {
        user_id: org_names_from_department(by_id.get(department_id), by_id)
        for user_id, department_id in primary_department_id.items()
    }


async def list_user_org_options() -> dict[str, list[str]]:
    """下拉只读有效组织, 不扫描审计日志."""
    rows = await DepartmentDao.aget_all_active()
    by_id = {int(row.id): row for row in rows if row.id is not None}
    buckets: dict[str, set[str]] = {"departments": set(), "companies": set(), "offices": set()}
    for row in by_id.values():
        key = _OPTION_KEYS.get(resolved_org_level(row, by_id))
        name = _clean_name(getattr(row, "name", None))
        if key and name:
            buckets[key].add(name)
    return {key: sorted(names) for key, names in buckets.items()}


def _matches_level(node: Any, level: str, departments_by_id: dict[int, Any]) -> bool:
    return _active(node) and resolved_org_level(node, departments_by_id) == level


async def _user_ids_for_level_name(level: str, name: str) -> set[int]:
    rows = await DepartmentDao.aget_by_name(name)
    if not rows:
        return set()
    by_id = {int(row.id): row for row in rows if row.id is not None}
    missing: set[int] = set()
    for row in rows:
        if str(getattr(row, "org_level", "") or ""):
            continue
        missing.update(path_ids(getattr(row, "path", None)))
    missing -= set(by_id)
    if missing:
        ancestors = await DepartmentDao.aget_by_ids(sorted(missing))
        for row in ancestors:
            if row.id is not None:
                by_id[int(row.id)] = row
    department_ids: set[int] = set()
    for row in rows:
        if row.id is None or not _matches_level(row, level, by_id):
            continue
        department_ids.add(int(row.id))
        path = str(getattr(row, "path", "") or "")
        # An empty path would become LIKE '%' and match every department.
        if path:
            department_ids.update(await DepartmentDao.aget_subtree_ids(path))
    if not department_ids:
        return set()
    user_ids = await UserDepartmentDao.aget_primary_user_ids_by_department_ids(sorted(department_ids))
    return {int(user_id) for user_id in user_ids}


async def user_ids_for_org_filters(
    user_department: str | None = None,
    user_company: str | None = None,
    user_office: str | None = None,
) -> set[int] | None:
    """None means the caller did not filter by organization.

    An empty set means the names match no primary-department user, so the
    audit query must not run.
    """
    selected = [
        (level, _clean_name(name))
        for level, name in (
            ("dept", user_department),
            ("company", user_company),
            ("office", user_office),
        )
        if _clean_name(name)
    ]
    if not selected:
        return None
    matched: set[int] | None = None
    for level, name in selected:
        ids = await _user_ids_for_level_name(level, name)
        matched = ids if matched is None else matched & ids
        if not matched:
            return set()
    return matched
