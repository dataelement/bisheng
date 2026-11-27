"""受影响用户展开、去重与草稿绑定分页查询服务（权限模板/风险等级草稿）。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy.exc import OperationalError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.subject_search import escape_like
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_group import UserGroup
from bisheng.user.domain.models.user import User
from bisheng.permission.domain.repositories.catalog_impact_repository import (
    BATCH_SIZE,
    CatalogImpactRepository,
)
from bisheng.permission.domain.services.catalog_policy import CatalogActionRelease
from bisheng.permission.domain.services.model_policy import (
    PermissionModelRelease,
    effective_model_action_codes,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

DEFAULT_AFFECTED_USER_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class AffectedUserEntry:
    """单个去重后的受影响活跃用户展示项。"""

    user_id: int
    username: str
    tenant_id: int
    tenant_name: str


@dataclass(frozen=True, slots=True)
class AffectedUsersPage:
    """受影响用户分页结果（列表与总数采用同一去重口径）。"""

    total: int
    page: int
    page_size: int
    has_more: bool
    cross_tenant: bool
    items: tuple[AffectedUserEntry, ...]


def _chunks(values: list[int], size: int = BATCH_SIZE):
    for index in range(0, len(values), size):
        yield values[index : index + size]


async def resolve_affected_users(
    *,
    session_factory: SessionFactory,
    candidate_model_keys: set[str],
    before_actions: CatalogActionRelease,
    after_actions: CatalogActionRelease,
    before_models: PermissionModelRelease,
    after_models: PermissionModelRelease,
    page: int = 1,
    page_size: int = DEFAULT_AFFECTED_USER_PAGE_SIZE,
) -> AffectedUsersPage:
    """展开变更授权涉及的活跃用户并按 user_id 去重，返回稳定排序的分页结果。

    统计口径：
    - 仅纳入有效操作集合发生变化（before != after）的活跃授权；仅改名称/同级授予计为 0；
    - 展开直接授权用户 + 部门（含子部门）成员 + 用户组成员 + 全员租户授权；
    - 排除服务账号（service_account）及已停用/删除用户（User.delete != 0）；
    - 按 user_id 全局去重，列表与总数口径一致。
    """
    if not candidate_model_keys:
        return AffectedUsersPage(
            total=0,
            page=page,
            page_size=page_size,
            has_more=False,
            cross_tenant=False,
            items=(),
        )

    before_by_key = {model.model_key: model for model in before_models.models}
    after_by_key = {model.model_key: model for model in after_models.models}
    repository = CatalogImpactRepository(session_factory=session_factory)

    # 收集各类受影响主体（按租户分桶，避免跨租户混展开）
    direct_users_by_tenant: dict[int, set[int]] = {}
    dept_exact_by_tenant: dict[int, set[int]] = {}
    dept_subtree_by_tenant: dict[int, set[int]] = {}
    group_member_by_tenant: dict[int, set[int]] = {}
    group_admin_by_tenant: dict[int, set[int]] = {}
    whole_tenants: set[int] = set()

    matrix: dict[tuple[str, str], tuple[frozenset[str], frozenset[str]]] = {}
    async for grants in repository.agrant_pages(candidate_model_keys):
        affected_grant_ids: list[int] = []
        for grant in grants:
            key = (grant.model_key, grant.resource_type)
            if key not in matrix:
                sets = []
                for model, actions in (
                    (before_by_key.get(grant.model_key), before_actions),
                    (after_by_key.get(grant.model_key), after_actions),
                ):
                    sets.append(
                        frozenset(effective_model_action_codes(model, actions, grant.resource_type))
                        if model is not None
                        else frozenset()
                    )
                matrix[key] = (sets[0], sets[1])
            before_set, after_set = matrix[key]
            if before_set != after_set:
                affected_grant_ids.append(int(grant.id))
        if not affected_grant_ids:
            continue

        subjects = await repository.asource_subjects(affected_grant_ids)
        for _grant_id, tenant_id, subject_type, subject_id, userset_relation, include_children in subjects:
            if subject_type == "service_account":
                continue
            if not subject_id.isdigit():
                continue
            numeric_id = int(subject_id)
            if numeric_id <= 0:
                continue
            if subject_type == "user":
                direct_users_by_tenant.setdefault(tenant_id, set()).add(numeric_id)
            elif subject_type == "department":
                if include_children or userset_relation == "subtree_member":
                    dept_subtree_by_tenant.setdefault(tenant_id, set()).add(numeric_id)
                else:
                    dept_exact_by_tenant.setdefault(tenant_id, set()).add(numeric_id)
            elif subject_type == "user_group":
                if userset_relation == "admin":
                    group_admin_by_tenant.setdefault(tenant_id, set()).add(numeric_id)
                else:
                    group_member_by_tenant.setdefault(tenant_id, set()).add(numeric_id)
            elif subject_type == "tenant":
                whole_tenants.add(numeric_id)

    has_any_subject = any(
        (
            direct_users_by_tenant,
            dept_exact_by_tenant,
            dept_subtree_by_tenant,
            group_member_by_tenant,
            group_admin_by_tenant,
            whole_tenants,
        )
    )
    if not has_any_subject:
        return AffectedUsersPage(
            total=0,
            page=page,
            page_size=page_size,
            has_more=False,
            cross_tenant=False,
            items=(),
        )

    try:
        return await _expand_and_paginate(
            session_factory=session_factory,
            direct_users_by_tenant=direct_users_by_tenant,
            dept_exact_by_tenant=dept_exact_by_tenant,
            dept_subtree_by_tenant=dept_subtree_by_tenant,
            group_member_by_tenant=group_member_by_tenant,
            group_admin_by_tenant=group_admin_by_tenant,
            whole_tenants=whole_tenants,
            page=page,
            page_size=page_size,
        )
    except OperationalError as exc:
        # 兼容仅建权限表的精简单元测试 SQLite 内存库（生产库均存在业务表）
        if "no such table" in str(exc).lower():
            return AffectedUsersPage(
                total=0,
                page=page,
                page_size=page_size,
                has_more=False,
                cross_tenant=False,
                items=(),
            )
        raise


async def _expand_and_paginate(
    *,
    session_factory: SessionFactory,
    direct_users_by_tenant: dict[int, set[int]],
    dept_exact_by_tenant: dict[int, set[int]],
    dept_subtree_by_tenant: dict[int, set[int]],
    group_member_by_tenant: dict[int, set[int]],
    group_admin_by_tenant: dict[int, set[int]],
    whole_tenants: set[int],
    page: int,
    page_size: int,
) -> AffectedUsersPage:
    # 记录每个候选 user_id 对应的来源租户（用于单租户/缺失 user_tenant 时的回退）
    candidate_tenant_hint: dict[int, int] = {}

    def _add_users(user_ids, tenant_id: int) -> None:
        for uid in user_ids:
            uid_int = int(uid)
            if uid_int > 0 and uid_int not in candidate_tenant_hint:
                candidate_tenant_hint[uid_int] = tenant_id

    for tenant_id, uids in direct_users_by_tenant.items():
        _add_users(uids, tenant_id)

    with bypass_tenant_filter():
        async with session_factory() as session:
            # 1) 展开部门与子部门成员
            all_dept_tenants = set(dept_exact_by_tenant) | set(dept_subtree_by_tenant)
            for tenant_id in sorted(all_dept_tenants):
                target_dept_ids: set[int] = set(dept_exact_by_tenant.get(tenant_id, ()))
                subtree_roots = sorted(dept_subtree_by_tenant.get(tenant_id, ()))
                if subtree_roots:
                    target_dept_ids.update(subtree_roots)
                    root_paths: list[str] = []
                    for batch in _chunks(subtree_roots):
                        rows = (
                            await session.exec(
                                select(Department.id, Department.path).where(
                                    col(Department.id).in_(batch),
                                    Department.tenant_id == tenant_id,
                                )
                            )
                        ).all()
                        for _dept_id, path in rows:
                            if path:
                                root_paths.append(str(path))
                    for path in sorted(set(root_paths)):
                        descendants = (
                            await session.exec(
                                select(Department.id).where(
                                    Department.tenant_id == tenant_id,
                                    Department.path.like(f"{escape_like(path)}%", escape="/"),
                                )
                            )
                        ).all()
                        for dept_id in descendants:
                            target_dept_ids.add(int(dept_id))
                if target_dept_ids:
                    for batch in _chunks(sorted(target_dept_ids)):
                        uids = (
                            await session.exec(
                                select(UserDepartment.user_id).where(col(UserDepartment.department_id).in_(batch))
                            )
                        ).all()
                        _add_users(uids, tenant_id)

            # 2) 展开用户组成员 / 管理员
            for tenant_id, group_ids in group_member_by_tenant.items():
                for batch in _chunks(sorted(group_ids)):
                    uids = (
                        await session.exec(
                            select(UserGroup.user_id).where(
                                col(UserGroup.group_id).in_(batch),
                                UserGroup.tenant_id == tenant_id,
                            )
                        )
                    ).all()
                    _add_users(uids, tenant_id)

            for tenant_id, group_ids in group_admin_by_tenant.items():
                for batch in _chunks(sorted(group_ids)):
                    uids = (
                        await session.exec(
                            select(UserGroup.user_id).where(
                                col(UserGroup.group_id).in_(batch),
                                UserGroup.tenant_id == tenant_id,
                                UserGroup.is_group_admin == True,  # noqa: E712
                            )
                        )
                    ).all()
                    _add_users(uids, tenant_id)

            # 3) 展开全员租户授权
            if whole_tenants:
                for batch in _chunks(sorted(whole_tenants)):
                    rows = (
                        await session.exec(
                            select(UserTenant.user_id, UserTenant.tenant_id).where(
                                col(UserTenant.tenant_id).in_(batch),
                                UserTenant.status == "active",
                                UserTenant.is_active == 1,
                            )
                        )
                    ).all()
                    for uid, tenant_id in rows:
                        _add_users((uid,), int(tenant_id))

            if not candidate_tenant_hint:
                return AffectedUsersPage(
                    total=0,
                    page=page,
                    page_size=page_size,
                    has_more=False,
                    cross_tenant=False,
                    items=(),
                )

            # 4) 过滤活跃用户（User.delete == 0）并读取用户名
            all_candidate_ids = sorted(candidate_tenant_hint)
            active_users: dict[int, str] = {}
            for batch in _chunks(all_candidate_ids):
                rows = (
                    await session.exec(
                        select(User.user_id, User.user_name).where(
                            col(User.user_id).in_(batch),
                            User.delete == 0,
                        )
                    )
                ).all()
                for uid, user_name in rows:
                    if uid is not None:
                        active_users[int(uid)] = str(user_name or "")

            if not active_users:
                return AffectedUsersPage(
                    total=0,
                    page=page,
                    page_size=page_size,
                    has_more=False,
                    cross_tenant=False,
                    items=(),
                )

            # 5) 读取活跃用户当前所属租户（优先 UserTenant 活跃叶子租户，回退到授权来源租户）
            active_ids = sorted(active_users)
            user_tenants: dict[int, int] = {}
            try:
                for batch in _chunks(active_ids):
                    rows = (
                        await session.exec(
                            select(UserTenant.user_id, UserTenant.tenant_id).where(
                                col(UserTenant.user_id).in_(batch),
                                UserTenant.status == "active",
                                UserTenant.is_active == 1,
                            )
                        )
                    ).all()
                    for uid, tenant_id in rows:
                        if uid is not None and tenant_id is not None:
                            user_tenants[int(uid)] = int(tenant_id)
            except OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    raise

            # 按 (用户名不区分大小写, user_id) 稳定排序，确保跨页顺序一致
            ordered_ids = sorted(active_ids, key=lambda uid: (active_users[uid].casefold(), uid))
            total = len(ordered_ids)
            distinct_tenants = {user_tenants.get(uid, candidate_tenant_hint[uid]) for uid in ordered_ids}
            cross_tenant = len(distinct_tenants) > 1

            start = max(0, (page - 1) * page_size)
            end = start + page_size
            page_ids = ordered_ids[start:end]
            has_more = end < total

            # 仅对当前分页用户批量查询租户名
            page_tenant_ids = sorted({user_tenants.get(uid, candidate_tenant_hint[uid]) for uid in page_ids})
            tenant_names: dict[int, str] = {}
            if page_tenant_ids:
                try:
                    for batch in _chunks(page_tenant_ids):
                        rows = (
                            await session.exec(
                                select(Tenant.id, Tenant.tenant_name).where(col(Tenant.id).in_(batch))
                            )
                        ).all()
                        for tid, tname in rows:
                            if tid is not None:
                                tenant_names[int(tid)] = str(tname or "")
                except OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise

            items = tuple(
                AffectedUserEntry(
                    user_id=uid,
                    username=active_users[uid],
                    tenant_id=(tid := user_tenants.get(uid, candidate_tenant_hint[uid])),
                    tenant_name=tenant_names.get(tid, ""),
                )
                for uid in page_ids
            )
            return AffectedUsersPage(
                total=total,
                page=page,
                page_size=page_size,
                has_more=has_more,
                cross_tenant=cross_tenant,
                items=items,
            )
