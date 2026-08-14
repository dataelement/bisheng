"""部门展示名称的统一只读投影。

F083 只消费 F082 的 ``Department.short_name``, 不在此处查询或修改部门数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DepartmentNameSource(Protocol):
    id: int | None
    name: str
    short_name: str | None


@dataclass(frozen=True, slots=True)
class DepartmentNameProjection:
    department_id: int | None
    name: str
    short_name: str | None
    display_name: str


def normalize_department_short_name(short_name: str | None) -> str | None:
    """规范化简称; 空字符串和纯空白统一视为未设置。"""

    if short_name is None:
        return None
    normalized = short_name.strip()
    return normalized or None


def get_department_display_name(name: str, short_name: str | None) -> str:
    """返回门户展示名称, 简称缺失时回退正式名称。"""

    return normalize_department_short_name(short_name) or name


def build_department_name_projection(
    department: DepartmentNameSource,
) -> DepartmentNameProjection:
    """从已加载的部门对象构造兼容投影, 不触发额外查询。"""

    return build_department_name_projection_from_values(
        department_id=getattr(department, "id", None),
        name=department.name,
        short_name=getattr(department, "short_name", None),
    )


def build_department_name_projection_from_values(
    *,
    department_id: int | None,
    name: str,
    short_name: str | None,
) -> DepartmentNameProjection:
    """从批量查询结果构造部门名称投影。"""

    normalized_short_name = normalize_department_short_name(short_name)
    return DepartmentNameProjection(
        department_id=department_id,
        name=name,
        short_name=normalized_short_name,
        display_name=normalized_short_name or name,
    )


def department_display_sort_key(
    department: DepartmentNameSource,
) -> tuple[str, str, int]:
    """按展示名、正式名和稳定部门 ID 生成确定性排序键。"""

    department_id_value = getattr(department, "id", None)
    department_id = department_id_value if department_id_value is not None else -1
    return (
        get_department_display_name(department.name, getattr(department, "short_name", None)),
        department.name,
        department_id,
    )
