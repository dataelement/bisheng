"""科室知识库绑定：组织树裁剪与可选科室判定。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

CLINIC_BIND_ORG_LEVEL = "office"
CLINIC_TREE_ORG_LEVELS = frozenset({"company", "dept", "office"})
CLINIC_BIND_DENIED_MSG = "科室知识库只能绑定科室级组织"


def org_level_of(dept: Any) -> str:
    """读取组织层级标签；空值视为未打标。"""
    return str(getattr(dept, "org_level", None) or "")


def is_clinic_bindable_department(dept: Any) -> bool:
    """是否可作为科室库绑定目标：必须是 office。"""
    return org_level_of(dept) == CLINIC_BIND_ORG_LEVEL


def _department_id(dept: Any) -> int | None:
    raw = getattr(dept, "id", None)
    if raw is None:
        return None
    return int(raw)


def _parse_path_ids(path: Any) -> list[int]:
    return [int(part) for part in str(path or "").split("/") if part.isdigit()]


def _has_office_ancestor(*, dept: Any, by_id: dict[int, Any], office_ids: set[int]) -> bool:
    """父链（含 path 祖先）上已有 office 时，当前节点视为科室以下。"""
    dept_id = _department_id(dept)
    for path_id in _parse_path_ids(getattr(dept, "path", None)):
        if path_id != dept_id and path_id in office_ids:
            return True
    parent_id = getattr(dept, "parent_id", None)
    seen: set[int] = set()
    while parent_id is not None:
        pid = int(parent_id)
        if pid in seen:
            break
        seen.add(pid)
        if pid in office_ids:
            return True
        parent = by_id.get(pid)
        if parent is None:
            break
        parent_id = getattr(parent, "parent_id", None)
    return False


def _nearest_kept_parent(*, dept: Any, by_id: dict[int, Any], kept_ids: set[int]) -> int | None:
    """父节点被裁掉时，挂到最近仍保留的祖先；没有则作为根。"""
    parent_id = getattr(dept, "parent_id", None)
    seen: set[int] = set()
    while parent_id is not None:
        pid = int(parent_id)
        if pid in seen:
            break
        seen.add(pid)
        if pid in kept_ids:
            return pid
        parent = by_id.get(pid)
        if parent is None:
            break
        parent_id = getattr(parent, "parent_id", None)
    return None


def filter_clinic_bind_tree_departments(departments: list[Any]) -> list[SimpleNamespace]:
    """把可见组织裁成「最多到 office」的展示树数据。

    保留 company / dept / office；丢掉 squad、未打标、以及 office 以下的后代。
    不按树深度猜测科室。父节点被裁时改挂到最近保留祖先。
    """
    by_id: dict[int, Any] = {}
    for dept in departments:
        dept_id = _department_id(dept)
        if dept_id is None:
            continue
        by_id[dept_id] = dept

    office_ids = {dept_id for dept_id, dept in by_id.items() if org_level_of(dept) == CLINIC_BIND_ORG_LEVEL}

    kept: list[Any] = []
    for dept in by_id.values():
        if org_level_of(dept) not in CLINIC_TREE_ORG_LEVELS:
            continue
        if _has_office_ancestor(dept=dept, by_id=by_id, office_ids=office_ids):
            continue
        kept.append(dept)

    kept_ids = {_department_id(dept) for dept in kept if _department_id(dept) is not None}
    result: list[SimpleNamespace] = []
    for dept in kept:
        dept_id = _department_id(dept)
        if dept_id is None:
            continue
        result.append(
            SimpleNamespace(
                id=dept_id,
                dept_id=getattr(dept, "dept_id", "") or "",
                name=getattr(dept, "name", "") or "",
                short_name=getattr(dept, "short_name", None),
                parent_id=_nearest_kept_parent(dept=dept, by_id=by_id, kept_ids=kept_ids),
                path=getattr(dept, "path", None),
                sort_order=int(getattr(dept, "sort_order", 0) or 0),
                org_level=org_level_of(dept),
                status=getattr(dept, "status", "active"),
            )
        )
    return result
