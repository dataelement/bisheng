"""库与文件夹拖拽排序鉴权, 以及列表 can_reorder 标志.

工作集规则见 F106 design.md. 运营岗只用 has_platform_operator_role, 禁止写入 is_admin().
TEAM 工作集不得用 can_platform_operate (其中含超管, 会让运营岗排到团队库).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from bisheng.common.errcode.knowledge_space import SpaceInvalidLevelError, SpacePermissionDeniedError
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum, KnowledgeSpaceScopeDao
from bisheng.user.domain.services.platform_operator import has_platform_operator_role

TEAM_GROUP_LEVELS = (KnowledgeSpaceLevelEnum.TEAM, KnowledgeSpaceLevelEnum.TEAM_KS)
PUBLIC_OR_DEPARTMENT = frozenset(
    {KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceLevelEnum.DEPARTMENT},
)


def is_system_admin(user: Any) -> bool:
    """系统管理员判定, 与 login_user.is_admin() 对齐, 不把运营岗算进来."""
    if user is None:
        return False
    check = getattr(user, "is_admin", None)
    if callable(check):
        return bool(check())
    return bool(check)


def _space_id(item: Any) -> int:
    if isinstance(item, dict):
        return int(item["id"])
    return int(item.id)


def _space_level(item: Any) -> KnowledgeSpaceLevelEnum | None:
    raw = item.get("space_level") if isinstance(item, dict) else getattr(item, "space_level", None)
    if raw is None:
        return None
    value = getattr(raw, "value", raw)
    try:
        return KnowledgeSpaceLevelEnum(str(value))
    except ValueError:
        return None


def _set_can_reorder(item: Any, flag: bool) -> None:
    if isinstance(item, dict):
        item["can_reorder"] = flag
        return
    item.can_reorder = flag


async def resolve_space_reorder_workset_ids(
    login_user: Any,
    *,
    dragged_level: KnowledgeSpaceLevelEnum,
    visible_space_ids: set[int] | None = None,
    admin_department_ids: set[int] | None = None,
) -> set[int]:
    """当前用户可改序的空间 ID.

    visible_space_ids 为 None 表示不再与可见集求交 (系统管理员 / 运营岗的 PUBLIC|DEPARTMENT).
    部门管理员 TEAM 必须传入管辖部门 ID, 并与绑定表、可见集求交.
    """
    if dragged_level == KnowledgeSpaceLevelEnum.PERSONAL:
        return set()

    if dragged_level in PUBLIC_OR_DEPARTMENT:
        if is_system_admin(login_user) or has_platform_operator_role(login_user):
            ids = await KnowledgeSpaceScopeDao.aget_space_ids_by_level(dragged_level)
            return {int(space_id) for space_id in ids}
        return set()

    if dragged_level not in TEAM_GROUP_LEVELS:
        return set()

    if is_system_admin(login_user):
        ids = await KnowledgeSpaceScopeDao.aget_space_ids_by_levels(list(TEAM_GROUP_LEVELS))
        return {int(space_id) for space_id in ids}

    # 运营岗不能排团队/科室库. 这里不能用 can_platform_operate.
    if has_platform_operator_role(login_user):
        return set()

    if not admin_department_ids:
        return set()

    bindings = await DepartmentKnowledgeSpaceDao.aget_by_department_ids(list(admin_department_ids))
    bound_ids = {int(row.space_id) for row in bindings}
    if not bound_ids:
        return set()
    team_ids = {
        int(space_id) for space_id in await KnowledgeSpaceScopeDao.aget_space_ids_by_levels(list(TEAM_GROUP_LEVELS))
    }
    workset = bound_ids & team_ids
    if visible_space_ids is not None:
        workset &= visible_space_ids
    return workset


def assert_space_in_workset(space_id: int, workset: set[int]) -> None:
    """被拖库不在工作集则 18040."""
    if int(space_id) not in workset:
        raise SpacePermissionDeniedError()


def assert_neighbours_in_workset(
    prev_space_id: int | None,
    next_space_id: int | None,
    workset: set[int],
) -> None:
    """邻居不在本次工作集则 18041 (跨组或过期视图)."""
    for neighbour_id in (prev_space_id, next_space_id):
        if neighbour_id is not None and int(neighbour_id) not in workset:
            raise SpaceInvalidLevelError()


async def can_reorder_folders(
    login_user: Any,
    *,
    space_id: int,
    parent_folder_id: int | None,
) -> bool:
    """当前父目录是否允许拖文件夹. 根目录鉴权知识空间, 子目录鉴权该文件夹."""
    from bisheng.permission.domain.services.permission_service import PermissionService

    user_id = int(login_user.user_id)
    if parent_folder_id is None:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_manage",
            object_type="knowledge_space",
            object_id=str(space_id),
            login_user=login_user,
        )
    return await PermissionService.check(
        user_id=user_id,
        relation="can_manage",
        object_type="folder",
        object_id=str(parent_folder_id),
        login_user=login_user,
    )


async def assert_can_reorder_folders(
    login_user: Any,
    *,
    space_id: int,
    parent_folder_id: int | None,
) -> None:
    """文件夹写接口鉴权失败则 18040."""
    allowed = await can_reorder_folders(
        login_user,
        space_id=space_id,
        parent_folder_id=parent_folder_id,
    )
    if not allowed:
        raise SpacePermissionDeniedError()


def folder_parent_id(file_level_path: str | None) -> int | None:
    """file_level_path 最后一段为父文件夹 ID, 空路径表示库根."""
    ancestor_ids = [int(part) for part in (file_level_path or "").split("/") if part]
    return ancestor_ids[-1] if ancestor_ids else None


async def attach_can_reorder_flags(
    login_user: Any,
    items: Sequence[Any],
    *,
    admin_department_ids: set[int],
    visible_space_ids: set[int] | None = None,
) -> None:
    """给列表/详情项写入 can_reorder. 每个 level 只算一次工作集, 禁止按库 N+1."""
    if not items:
        return
    levels: set[KnowledgeSpaceLevelEnum] = set()
    for item in items:
        level = _space_level(item)
        if level is not None:
            levels.add(level)
    listed_ids = {_space_id(item) for item in items}
    visible = listed_ids if visible_space_ids is None else visible_space_ids
    workset: set[int] = set()
    for level in levels:
        workset |= await resolve_space_reorder_workset_ids(
            login_user,
            dragged_level=level,
            visible_space_ids=visible,
            admin_department_ids=admin_department_ids,
        )
    for item in items:
        _set_can_reorder(item, _space_id(item) in workset)


def collect_item_ids(items: Iterable[Any]) -> set[int]:
    """从列表项取出 ID, 供调用方做可见集."""
    return {_space_id(item) for item in items}
