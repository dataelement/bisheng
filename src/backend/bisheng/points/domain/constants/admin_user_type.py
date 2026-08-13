"""管理端用户积分列表「用户类型」展示（对齐 PRD 4.3.4.1）。"""

from __future__ import annotations

from sqlmodel import select

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao

USER_TYPE_NORMAL = "普通用户"
USER_TYPE_TEAM_KS_ADMIN = "科室库管理员"
USER_TYPE_DEPT_ADMIN = "部门库管理员"
USER_TYPE_PUBLIC_ADMIN = "公共库管理员"

LEVEL_TO_USER_TYPE: dict[str, str] = {
    "public": USER_TYPE_PUBLIC_ADMIN,
    "department": USER_TYPE_DEPT_ADMIN,
    "team_ks": USER_TYPE_TEAM_KS_ADMIN,
}

USER_TYPE_PRIORITY: dict[str, int] = {
    USER_TYPE_NORMAL: 0,
    USER_TYPE_TEAM_KS_ADMIN: 1,
    USER_TYPE_DEPT_ADMIN: 2,
    USER_TYPE_PUBLIC_ADMIN: 3,
}

# PRD 角色下拉选项（不含「全部角色」占位）
USER_TYPE_FILTER_OPTIONS: tuple[str, ...] = (
    USER_TYPE_NORMAL,
    USER_TYPE_TEAM_KS_ADMIN,
    USER_TYPE_DEPT_ADMIN,
    USER_TYPE_PUBLIC_ADMIN,
)


def pick_highest_user_type(labels: list[str]) -> str:
    """多角色兼任时取最高档管理员类型；无管理员角色则为普通用户。"""
    if not labels:
        return USER_TYPE_NORMAL
    return max(labels, key=lambda item: USER_TYPE_PRIORITY.get(item, 0))


def _labels_by_user_from_members(
    members: list[SpaceChannelMember],
    scope_map: dict[int, object],
) -> dict[int, list[str]]:
    """从空间成员与库级映射汇总每位用户的管理员标签。"""
    labels_by_user: dict[int, list[str]] = {}
    for member in members:
        uid = int(member.user_id)
        try:
            space_id = int(member.business_id)
        except (TypeError, ValueError):
            continue
        scope = scope_map.get(space_id)
        if scope is None:
            continue
        level = getattr(scope.level, "value", scope.level)
        label = LEVEL_TO_USER_TYPE.get(str(level))
        if label:
            labels_by_user.setdefault(uid, []).append(label)
    return labels_by_user


async def _load_space_admin_members(user_ids: list[int] | None = None) -> list[SpaceChannelMember]:
    """列出在 public/department/team_ks 空间担任 creator/admin 的成员行。"""
    async with get_async_db_session() as session:
        statement = select(SpaceChannelMember).where(
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            SpaceChannelMember.user_role.in_([UserRoleEnum.CREATOR, UserRoleEnum.ADMIN]),
        )
        if user_ids is not None:
            if not user_ids:
                return []
            statement = statement.where(SpaceChannelMember.user_id.in_(user_ids))
        return list((await session.exec(statement)).all())


async def load_admin_user_type_map() -> dict[int, str]:
    """全量解析有库管理员身份的用户 → 最高档 PRD 用户类型。"""
    members = await _load_space_admin_members()
    space_ids: list[int] = []
    for member in members:
        try:
            space_ids.append(int(member.business_id))
        except (TypeError, ValueError):
            continue
    scope_map = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(space_ids)
    labels_by_user = _labels_by_user_from_members(members, scope_map)
    return {uid: pick_highest_user_type(labels) for uid, labels in labels_by_user.items()}


async def resolve_user_ids_for_user_type_filter(
    user_type: str,
    *,
    account_user_ids: list[int],
) -> list[int] | None:
    """按 PRD 用户类型筛 user_id；空串/未知值返回 None 表示不过滤。"""
    label = (user_type or "").strip()
    if not label or label not in USER_TYPE_PRIORITY:
        return None

    admin_map = await load_admin_user_type_map()
    if label == USER_TYPE_NORMAL:
        admin_uids = {uid for uid, mapped in admin_map.items() if mapped != USER_TYPE_NORMAL}
        return sorted(set(account_user_ids) - admin_uids)
    return sorted(uid for uid, mapped in admin_map.items() if mapped == label)


async def resolve_user_types_for_admin_list(user_ids: list[int]) -> dict[int, str]:
    """批量解析用户类型：空间 creator/admin × 库级 → PRD 四类文案。"""
    if not user_ids:
        return {}

    members = await _load_space_admin_members(user_ids)
    space_ids: list[int] = []
    for member in members:
        try:
            space_ids.append(int(member.business_id))
        except (TypeError, ValueError):
            continue
    scope_map = await KnowledgeSpaceScopeDao.aget_map_by_space_ids(space_ids)
    labels_by_user = _labels_by_user_from_members(members, scope_map)

    return {uid: pick_highest_user_type(labels_by_user.get(uid, [])) for uid in user_ids}
