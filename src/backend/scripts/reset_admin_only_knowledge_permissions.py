#!/usr/bin/env python3
"""将系统权限重置为仅 admin 持有知识空间权限。

用途：

1. 校验且只接受一个可用的 ``user.user_name = 'admin'`` 用户。
2. 将除 admin 外的用户角色收敛为普通用户角色，并撤销租户、部门、用户组、
   个人菜单等管理授权。
3. 将所有知识空间、文件夹、文件的创建者改为 admin，删除非 admin 的资源授权，
   并为 admin 写入 owner 权限。
4. 失效知识空间文件分享链接，并使相关 pending ``failed_tuple`` 不再重试旧权限。

默认只 dry-run 统计影响范围；只有显式传入 ``--apply`` 才会写数据库和 OpenFGA。

运行方式：

    PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py
    PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py --apply
    bash scripts/reset_admin_only_knowledge_permissions.sh
    bash scripts/reset_admin_only_knowledge_permissions.sh --apply
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlmodel import select

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.approval.domain.models.user_menu_access import (  # noqa: E402
    UserMenuAccess,
    UserMenuAccessStatus,
)
from bisheng.common.models.config import Config  # noqa: E402
from bisheng.common.models.space_channel_member import (  # noqa: E402
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.openfga.manager import aget_fga_client  # noqa: E402
from bisheng.database.constants import AdminRole, DefaultRole  # noqa: E402
from bisheng.database.models.department_admin_grant import (  # noqa: E402
    DepartmentAdminGrant,
)
from bisheng.database.models.failed_tuple import FailedTuple  # noqa: E402
from bisheng.database.models.tenant import ROOT_TENANT_ID, UserTenant  # noqa: E402
from bisheng.database.models.user_group import UserGroup  # noqa: E402
from bisheng.knowledge.domain.models.department_knowledge_space import (  # noqa: E402
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (  # noqa: E402
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.permission.domain.schemas.tuple_operation import (  # noqa: E402
    TupleOperation,
)
from bisheng.permission.domain.services.permission_cache import (  # noqa: E402
    PermissionCache,
)
from bisheng.permission.domain.services.permission_service import (  # noqa: E402
    PermissionService,
)
from bisheng.share_link.domain.models.share_link import (  # noqa: E402
    ResourceTypeEnum,
    ShareLink,
    ShareLinkStatusEnum,
)
from bisheng.user.domain.models.user import User  # noqa: E402
from bisheng.user.domain.models.user_role import UserRole  # noqa: E402


def _coerce_role_constant(value: Any, fallback: int) -> int:
    if isinstance(value, int):
        return value
    if type(value).__module__.startswith('unittest.mock'):
        return fallback
    try:
        parsed = int(value)
    except Exception:
        return fallback
    return parsed if parsed > 0 else fallback


ADMIN_ROLE_ID = _coerce_role_constant(AdminRole, 1)
DEFAULT_ROLE_ID = _coerce_role_constant(DefaultRole, 2)
RELATION_BINDINGS_CONFIG_KEY = 'permission_relation_model_bindings_v1'
RESET_FAILED_TUPLE_ERROR = 'invalidated by admin-only knowledge permission reset'
RESET_MENU_REVOKE_REASON = 'revoked by admin-only permission reset script'
MANAGEMENT_ADMIN_OBJECT_PREFIXES = ('tenant:', 'department:', 'user_group:')


class AdminResolutionError(RuntimeError):
    """admin 用户不满足唯一性要求时抛出。"""


@dataclass(frozen=True)
class FgaTupleKey:
    user: str
    relation: str
    object: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> 'FgaTupleKey':
        key = value.get('key') if isinstance(value.get('key'), dict) else value
        return cls(
            user=str(key.get('user') or ''),
            relation=str(key.get('relation') or ''),
            object=str(key.get('object') or ''),
        )

    def to_operation(self, action: str) -> TupleOperation:
        if action not in {'write', 'delete'}:
            raise ValueError(f'invalid tuple action: {action}')
        return TupleOperation(
            action=action,  # type: ignore[arg-type]
            user=self.user,
            relation=self.relation,
            object=self.object,
        )


@dataclass(frozen=True)
class ResourceRef:
    object_type: str
    object_id: str
    parent_type: str | None = None
    parent_id: str | None = None

    @property
    def object_key(self) -> str:
        return f'{self.object_type}:{self.object_id}'

    @property
    def resource_pair(self) -> tuple[str, str]:
        return self.object_type, self.object_id


@dataclass(frozen=True)
class UserRoleSnapshot:
    id: int | None
    user_id: int
    role_id: int
    tenant_id: int | None


@dataclass(frozen=True)
class UserRoleResetPlan:
    delete_role_ids: tuple[int, ...]
    default_role_inserts: tuple[tuple[int, int], ...]
    admin_role_missing: bool
    admin_role_tenant_id: int


@dataclass(frozen=True)
class ScopeInsert:
    space_id: int
    tenant_id: int


@dataclass(frozen=True)
class ResetPlan:
    admin_id: int
    admin_user_name: str
    non_admin_user_ids: tuple[int, ...]
    user_role_plan: UserRoleResetPlan
    group_admin_row_ids: tuple[int, ...]
    user_group_member_writes: tuple[FgaTupleKey, ...]
    knowledge_space_ids: tuple[int, ...]
    knowledge_file_ids: tuple[int, ...]
    resource_refs: tuple[ResourceRef, ...]
    resource_tuple_operations: tuple[TupleOperation, ...]
    management_tuple_operations: tuple[TupleOperation, ...]
    relation_bindings_kept: tuple[dict[str, Any], ...]
    relation_bindings_removed: tuple[dict[str, Any], ...]
    admin_member_insert_space_ids: tuple[int, ...]
    scope_inserts: tuple[ScopeInsert, ...]
    failed_tuple_ids_to_invalidate: tuple[int, ...]
    counts: dict[str, int]
    warnings: tuple[str, ...]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='真正执行写入；不传时只 dry-run 输出影响范围',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='以 JSON 格式输出汇总，便于保存审计记录',
    )
    return parser.parse_args(argv)


def validate_admin_user(candidates: Sequence[Any]) -> Any:
    active = [
        user for user in candidates
        if getattr(user, 'user_name', None) == 'admin'
        and int(getattr(user, 'delete', 0) or 0) == 0
    ]
    if len(active) != 1:
        raise AdminResolutionError(
            f"expected exactly one active admin user (user_name='admin' AND delete=0), got {len(active)}"
        )
    return active[0]


def plan_user_role_reset(
    *,
    admin_id: int,
    all_user_ids: Sequence[int],
    role_rows: Sequence[UserRoleSnapshot],
    active_tenant_by_user: dict[int, int],
) -> UserRoleResetPlan:
    by_user: dict[int, list[UserRoleSnapshot]] = {}
    for row in role_rows:
        by_user.setdefault(int(row.user_id), []).append(row)

    delete_ids: list[int] = []
    inserts: list[tuple[int, int]] = []
    for user_id in sorted({int(uid) for uid in all_user_ids if int(uid) != int(admin_id)}):
        rows = by_user.get(user_id, [])
        has_default = any(int(row.role_id) == DEFAULT_ROLE_ID for row in rows)
        for row in rows:
            if int(row.role_id) != DEFAULT_ROLE_ID and row.id is not None:
                delete_ids.append(int(row.id))
        if not has_default:
            inserts.append((user_id, _resolve_default_role_tenant(user_id, rows, active_tenant_by_user)))

    admin_rows = by_user.get(int(admin_id), [])
    admin_role_missing = not any(int(row.role_id) == ADMIN_ROLE_ID for row in admin_rows)
    admin_role_tenant_id = _resolve_default_role_tenant(int(admin_id), admin_rows, active_tenant_by_user)
    return UserRoleResetPlan(
        delete_role_ids=tuple(sorted(delete_ids)),
        default_role_inserts=tuple(sorted(set(inserts))),
        admin_role_missing=admin_role_missing,
        admin_role_tenant_id=admin_role_tenant_id,
    )


def _resolve_default_role_tenant(
    user_id: int,
    rows: Sequence[UserRoleSnapshot],
    active_tenant_by_user: dict[int, int],
) -> int:
    tenant_ids = sorted({int(row.tenant_id) for row in rows if row.tenant_id is not None})
    if tenant_ids:
        return tenant_ids[0]
    return int(active_tenant_by_user.get(int(user_id)) or ROOT_TENANT_ID)


def resource_refs_for_knowledge(
    *,
    space_ids: Sequence[int],
    files: Sequence[Any],
) -> tuple[ResourceRef, ...]:
    refs: list[ResourceRef] = [
        ResourceRef(object_type='knowledge_space', object_id=str(space_id))
        for space_id in sorted({int(space_id) for space_id in space_ids})
    ]
    for file_row in sorted(files, key=lambda item: int(getattr(item, 'id'))):
        file_id = int(getattr(file_row, 'id'))
        knowledge_id = int(getattr(file_row, 'knowledge_id'))
        file_type = int(getattr(file_row, 'file_type'))
        parent_type, parent_id = resolve_parent_ref(
            knowledge_id=knowledge_id,
            file_level_path=getattr(file_row, 'file_level_path', None),
        )
        refs.append(
            ResourceRef(
                object_type='folder' if file_type == FileType.DIR.value else 'knowledge_file',
                object_id=str(file_id),
                parent_type=parent_type,
                parent_id=parent_id,
            )
        )
    return tuple(refs)


def resolve_parent_ref(
    *,
    knowledge_id: int,
    file_level_path: str | None,
) -> tuple[str, str]:
    segments = [seg for seg in (file_level_path or '').split('/') if seg]
    if not segments:
        return 'knowledge_space', str(knowledge_id)
    last = segments[-1]
    if not last.isdigit():
        return 'knowledge_space', str(knowledge_id)
    return 'folder', last


def build_desired_resource_tuples(
    *,
    admin_id: int,
    resources: Sequence[ResourceRef],
) -> tuple[FgaTupleKey, ...]:
    desired: list[FgaTupleKey] = []
    for resource in resources:
        desired.append(
            FgaTupleKey(
                user=f'user:{int(admin_id)}',
                relation='owner',
                object=resource.object_key,
            )
        )
        if resource.parent_type and resource.parent_id:
            desired.append(
                FgaTupleKey(
                    user=f'{resource.parent_type}:{resource.parent_id}',
                    relation='parent',
                    object=resource.object_key,
                )
            )
    return tuple(_dedupe_tuple_keys(desired))


def plan_resource_tuple_operations(
    existing_tuples: Sequence[FgaTupleKey],
    desired_tuples: Sequence[FgaTupleKey],
) -> tuple[TupleOperation, ...]:
    existing = set(existing_tuples)
    desired = set(desired_tuples)
    protected_existing = {item for item in existing if item.relation == 'parent'}

    deletes = sorted(existing - desired - protected_existing, key=_tuple_sort_key)
    writes = sorted(desired - existing, key=_tuple_sort_key)
    return tuple(
        [item.to_operation('delete') for item in deletes]
        + [item.to_operation('write') for item in writes]
    )


def filter_relation_bindings(
    bindings: Sequence[dict[str, Any]],
    affected_resources: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for binding in bindings:
        pair = (
            str(binding.get('resource_type') or ''),
            str(binding.get('resource_id') or ''),
        )
        if pair in affected_resources:
            removed.append(binding)
        else:
            kept.append(binding)
    return kept, removed


def should_invalidate_failed_tuple(
    row: Any,
    *,
    admin_id: int,
    affected_resources: set[tuple[str, str]],
) -> bool:
    if str(getattr(row, 'status', '') or '') != 'pending':
        return False

    obj = str(getattr(row, 'object', '') or '')
    if _resource_pair_from_object(obj) in affected_resources:
        return True

    fga_user = str(getattr(row, 'fga_user', '') or '')
    if fga_user == f'user:{int(admin_id)}':
        return False

    relation = str(getattr(row, 'relation', '') or '')
    if relation == 'super_admin' and obj == 'system:global':
        return True
    if relation == 'admin' and obj.startswith(MANAGEMENT_ADMIN_OBJECT_PREFIXES):
        return True
    return False


def _resource_pair_from_object(object_key: str) -> tuple[str, str]:
    if ':' not in object_key:
        return object_key, ''
    object_type, object_id = object_key.split(':', 1)
    return object_type, object_id


def _dedupe_tuple_keys(items: Iterable[FgaTupleKey]) -> list[FgaTupleKey]:
    seen: set[FgaTupleKey] = set()
    output: list[FgaTupleKey] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _tuple_sort_key(item: FgaTupleKey) -> tuple[str, str, str]:
    return item.object, item.relation, item.user


def _dedupe_operations(operations: Iterable[TupleOperation]) -> tuple[TupleOperation, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    output: list[TupleOperation] = []
    for op in operations:
        key = (op.action, op.user, op.relation, op.object)
        if key in seen:
            continue
        seen.add(key)
        output.append(op)
    return tuple(output)


async def collect_reset_plan(*, require_fga: bool) -> ResetPlan:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            admin_candidates = list((await session.exec(
                select(User).where(User.user_name == 'admin', User.delete == 0)
            )).all())
            admin = validate_admin_user(admin_candidates)
            admin_id = int(admin.user_id)
            admin_user_name = str(admin.user_name)

            all_user_ids = [
                int(uid) for uid in (await session.exec(select(User.user_id))).all()
                if uid is not None
            ]
            non_admin_user_ids = tuple(sorted(uid for uid in all_user_ids if uid != admin_id))

            role_rows = [
                UserRoleSnapshot(
                    id=int(row.id) if row.id is not None else None,
                    user_id=int(row.user_id),
                    role_id=int(row.role_id),
                    tenant_id=int(row.tenant_id) if row.tenant_id is not None else None,
                )
                for row in (await session.exec(select(UserRole))).all()
            ]
            active_tenant_by_user = {
                int(row.user_id): int(row.tenant_id)
                for row in (await session.exec(
                    select(UserTenant).where(UserTenant.is_active == 1)
                )).all()
            }
            user_role_plan = plan_user_role_reset(
                admin_id=admin_id,
                all_user_ids=all_user_ids,
                role_rows=role_rows,
                active_tenant_by_user=active_tenant_by_user,
            )
            role_user_by_id = {
                int(row.id): int(row.user_id)
                for row in role_rows
                if row.id is not None
            }

            group_admin_rows = list((await session.exec(
                select(UserGroup).where(
                    UserGroup.user_id != admin_id,
                    UserGroup.is_group_admin == True,  # noqa: E712
                )
            )).all())
            group_admin_row_ids = tuple(
                sorted(int(row.id) for row in group_admin_rows if row.id is not None)
            )
            user_group_member_writes = tuple(_dedupe_tuple_keys(
                FgaTupleKey(
                    user=f'user:{int(row.user_id)}',
                    relation='member',
                    object=f'user_group:{int(row.group_id)}',
                )
                for row in group_admin_rows
                if row.group_id is not None
            ))

            spaces = list((await session.exec(
                select(Knowledge).where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
            )).all())
            knowledge_space_ids = tuple(sorted(int(space.id) for space in spaces if space.id is not None))
            files = await _select_knowledge_files(session, knowledge_space_ids)
            knowledge_file_ids = tuple(sorted(int(row.id) for row in files if row.id is not None))
            resource_refs = resource_refs_for_knowledge(
                space_ids=knowledge_space_ids,
                files=files,
            )
            affected_resources = {ref.resource_pair for ref in resource_refs}

            bindings = await _load_relation_bindings(session)
            relation_bindings_kept, relation_bindings_removed = filter_relation_bindings(
                bindings,
                affected_resources,
            )

            admin_member_insert_space_ids = await _plan_admin_space_member_inserts(
                session,
                admin_id=admin_id,
                space_ids=knowledge_space_ids,
            )
            scope_inserts = await _plan_scope_inserts(session, spaces)

            pending_failed = list((await session.exec(
                select(FailedTuple).where(FailedTuple.status == 'pending')
            )).all())
            failed_tuple_ids_to_invalidate = tuple(sorted(
                int(row.id)
                for row in pending_failed
                if row.id is not None and should_invalidate_failed_tuple(
                    row,
                    admin_id=admin_id,
                    affected_resources=affected_resources,
                )
            ))

            counts = await _collect_db_counts(
                session,
                admin_id=admin_id,
                space_ids=knowledge_space_ids,
            )

    warnings: list[str] = []
    fga = await aget_fga_client()
    if fga is None:
        message = 'OpenFGA client unavailable; dry-run cannot count existing FGA tuples'
        if require_fga:
            raise RuntimeError('OpenFGA client unavailable; aborting --apply to avoid leaving stale permissions')
        warnings.append(message)
        existing_resource_tuples: list[FgaTupleKey] = []
        existing_management_tuples: list[FgaTupleKey] = []
    else:
        existing_resource_tuples = await _read_resource_tuples(fga, resource_refs)
        existing_management_tuples = await _read_management_tuples(fga)

    desired_resource_tuples = build_desired_resource_tuples(
        admin_id=admin_id,
        resources=resource_refs,
    )
    resource_tuple_operations = plan_resource_tuple_operations(
        existing_resource_tuples,
        desired_resource_tuples,
    )
    management_tuple_operations = _plan_management_tuple_operations(
        admin_id=admin_id,
        existing_tuples=existing_management_tuples,
        user_group_member_writes=user_group_member_writes,
    )

    counts.update({
        'users_demoted_to_default_role': len(
            {role_user_by_id[row_id] for row_id in user_role_plan.delete_role_ids if row_id in role_user_by_id}
            | {user_id for user_id, _ in user_role_plan.default_role_inserts}
        ),
        'knowledge_resources': len(resource_refs),
        'resource_tuple_operations': len(resource_tuple_operations),
        'management_tuple_operations': len(management_tuple_operations),
        'relation_bindings_removed': len(relation_bindings_removed),
        'failed_tuples_invalidated': len(failed_tuple_ids_to_invalidate),
        'user_role_rows_deleted': len(user_role_plan.delete_role_ids),
        'default_role_rows_inserted': len(user_role_plan.default_role_inserts),
        'admin_role_rows_inserted': 1 if user_role_plan.admin_role_missing else 0,
        'user_group_admin_rows_demoted': len(group_admin_row_ids),
        'admin_space_member_rows_inserted': len(admin_member_insert_space_ids),
        'knowledge_space_scope_rows_inserted': len(scope_inserts),
    })

    return ResetPlan(
        admin_id=admin_id,
        admin_user_name=admin_user_name,
        non_admin_user_ids=non_admin_user_ids,
        user_role_plan=user_role_plan,
        group_admin_row_ids=group_admin_row_ids,
        user_group_member_writes=user_group_member_writes,
        knowledge_space_ids=knowledge_space_ids,
        knowledge_file_ids=knowledge_file_ids,
        resource_refs=resource_refs,
        resource_tuple_operations=resource_tuple_operations,
        management_tuple_operations=management_tuple_operations,
        relation_bindings_kept=tuple(relation_bindings_kept),
        relation_bindings_removed=tuple(relation_bindings_removed),
        admin_member_insert_space_ids=admin_member_insert_space_ids,
        scope_inserts=scope_inserts,
        failed_tuple_ids_to_invalidate=failed_tuple_ids_to_invalidate,
        counts=counts,
        warnings=tuple(warnings),
    )


async def _select_knowledge_files(session, space_ids: Sequence[int]) -> list[KnowledgeFile]:
    if not space_ids:
        return []
    result = await session.exec(
        select(KnowledgeFile).where(KnowledgeFile.knowledge_id.in_(list(space_ids)))
    )
    return list(result.all())


async def _load_relation_bindings(session) -> list[dict[str, Any]]:
    row = (await session.exec(
        select(Config).where(Config.key == RELATION_BINDINGS_CONFIG_KEY)
    )).first()
    if row is None or not (row.value or '').strip():
        return []
    try:
        data = json.loads(row.value or '[]')
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f'{RELATION_BINDINGS_CONFIG_KEY} contains invalid JSON; aborting to avoid overwriting it'
        ) from exc
    if not isinstance(data, list):
        raise RuntimeError(
            f'{RELATION_BINDINGS_CONFIG_KEY} must be a JSON list; aborting to avoid overwriting it'
        )
    return data


async def _plan_admin_space_member_inserts(
    session,
    *,
    admin_id: int,
    space_ids: Sequence[int],
) -> tuple[int, ...]:
    if not space_ids:
        return ()
    existing = (await session.exec(
        select(SpaceChannelMember.business_id).where(
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.business_id.in_([str(sid) for sid in space_ids]),
            SpaceChannelMember.user_id == admin_id,
        )
    )).all()
    existing_ids = {int(str(row[0] if isinstance(row, tuple) else row)) for row in existing}
    return tuple(sorted(set(space_ids) - existing_ids))


async def _plan_scope_inserts(session, spaces: Sequence[Knowledge]) -> tuple[ScopeInsert, ...]:
    if not spaces:
        return ()
    space_ids = [int(space.id) for space in spaces if space.id is not None]
    existing = (await session.exec(
        select(KnowledgeSpaceScope.space_id).where(KnowledgeSpaceScope.space_id.in_(space_ids))
    )).all()
    existing_ids = {int(row[0] if isinstance(row, tuple) else row) for row in existing}
    inserts = []
    for space in spaces:
        if space.id is None or int(space.id) in existing_ids:
            continue
        inserts.append(ScopeInsert(
            space_id=int(space.id),
            tenant_id=int(space.tenant_id or ROOT_TENANT_ID),
        ))
    return tuple(inserts)


async def _collect_db_counts(
    session,
    *,
    admin_id: int,
    space_ids: Sequence[int],
) -> dict[str, int]:
    counts = {
        'users_demoted_to_default_role': 0,
        'department_admin_grants_deleted': 0,
        'active_user_menu_access_revoked': 0,
        'knowledge_spaces_reowned': len(space_ids),
        'knowledge_files_reowned': 0,
        'non_admin_space_members_deleted': 0,
        'admin_space_member_rows_updated': 0,
        'knowledge_space_scope_rows_updated': 0,
        'department_space_bindings_deleted': 0,
        'knowledge_space_file_share_links_disabled': 0,
    }
    counts['department_admin_grants_deleted'] = len((await session.exec(
        select(DepartmentAdminGrant.id).where(DepartmentAdminGrant.user_id != admin_id)
    )).all())
    counts['active_user_menu_access_revoked'] = len((await session.exec(
        select(UserMenuAccess.id).where(
            UserMenuAccess.user_id != admin_id,
            UserMenuAccess.status == UserMenuAccessStatus.ACTIVE,
        )
    )).all())
    counts['knowledge_space_file_share_links_disabled'] = len((await session.exec(
        select(ShareLink.id).where(
            ShareLink.resource_type == ResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
            ShareLink.status == ShareLinkStatusEnum.ACTIVE,
        )
    )).all())
    if space_ids:
        space_id_strings = [str(sid) for sid in space_ids]
        counts['knowledge_files_reowned'] = len((await session.exec(
            select(KnowledgeFile.id).where(KnowledgeFile.knowledge_id.in_(list(space_ids)))
        )).all())
        counts['non_admin_space_members_deleted'] = len((await session.exec(
            select(SpaceChannelMember.id).where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.business_id.in_(space_id_strings),
                SpaceChannelMember.user_id != admin_id,
            )
        )).all())
        counts['admin_space_member_rows_updated'] = len((await session.exec(
            select(SpaceChannelMember.id).where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.business_id.in_(space_id_strings),
                SpaceChannelMember.user_id == admin_id,
            )
        )).all())
        counts['knowledge_space_scope_rows_updated'] = len((await session.exec(
            select(KnowledgeSpaceScope.id).where(KnowledgeSpaceScope.space_id.in_(list(space_ids)))
        )).all())
        counts['department_space_bindings_deleted'] = len((await session.exec(
            select(DepartmentKnowledgeSpace.id).where(DepartmentKnowledgeSpace.space_id.in_(list(space_ids)))
        )).all())
    return counts


async def _read_resource_tuples(fga, resources: Sequence[ResourceRef]) -> list[FgaTupleKey]:
    output: list[FgaTupleKey] = []
    for resource in resources:
        tuples = await fga.read_tuples(object=resource.object_key)
        output.extend(FgaTupleKey.from_mapping(item) for item in tuples)
    return _dedupe_tuple_keys(output)


async def _read_management_tuples(fga) -> list[FgaTupleKey]:
    tuples = await fga.read_tuples(relation='admin')
    tuples.extend(await fga.read_tuples(relation='super_admin', object='system:global'))
    return _dedupe_tuple_keys(FgaTupleKey.from_mapping(item) for item in tuples)


def _plan_management_tuple_operations(
    *,
    admin_id: int,
    existing_tuples: Sequence[FgaTupleKey],
    user_group_member_writes: Sequence[FgaTupleKey],
) -> tuple[TupleOperation, ...]:
    admin_user = f'user:{int(admin_id)}'
    deletes: list[FgaTupleKey] = []
    existing = set(existing_tuples)
    for item in existing:
        if item.user == admin_user:
            continue
        if item.relation == 'super_admin' and item.object == 'system:global':
            deletes.append(item)
        elif item.relation == 'admin' and item.object.startswith(MANAGEMENT_ADMIN_OBJECT_PREFIXES):
            deletes.append(item)

    writes = [
        FgaTupleKey(user=admin_user, relation='super_admin', object='system:global'),
        *user_group_member_writes,
    ]
    write_ops = [
        item.to_operation('write')
        for item in sorted(set(writes) - existing, key=_tuple_sort_key)
    ]
    delete_ops = [
        item.to_operation('delete')
        for item in sorted(deletes, key=_tuple_sort_key)
    ]
    return _dedupe_operations([*delete_ops, *write_ops])


async def apply_reset_plan(plan: ResetPlan) -> None:
    operations = _dedupe_operations([
        *plan.resource_tuple_operations,
        *plan.management_tuple_operations,
    ])
    pre_recorded_ids = await _apply_db_changes(plan, operations)
    try:
        await PermissionService.batch_write_tuples(
            list(operations),
            crash_safe=False,
            raise_on_failure=True,
            stop_on_failure=False,
        )
    except Exception as exc:
        raise RuntimeError(
            'Database changes were committed, but OpenFGA tuple reset failed. '
            f'{len(pre_recorded_ids)} pre-recorded failed_tuple rows remain pending; '
            'retry the failed_tuple queue or re-run this script with --apply before treating the reset as complete.'
        ) from exc
    await _mark_reset_failed_tuples_succeeded(pre_recorded_ids)
    await _invalidate_permission_caches(plan)


async def _apply_db_changes(plan: ResetPlan, operations: Sequence[TupleOperation]) -> tuple[int, ...]:
    now = datetime.now()
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            if plan.user_role_plan.delete_role_ids:
                await session.execute(
                    sa_delete(UserRole).where(UserRole.id.in_(list(plan.user_role_plan.delete_role_ids)))
                )
            for user_id, tenant_id in plan.user_role_plan.default_role_inserts:
                session.add(UserRole(
                    user_id=user_id,
                    role_id=DEFAULT_ROLE_ID,
                    tenant_id=tenant_id,
                ))
            if plan.user_role_plan.admin_role_missing:
                session.add(UserRole(
                    user_id=plan.admin_id,
                    role_id=ADMIN_ROLE_ID,
                    tenant_id=plan.user_role_plan.admin_role_tenant_id,
                ))

            await session.execute(
                sa_update(UserGroup)
                .where(UserGroup.user_id != plan.admin_id, UserGroup.is_group_admin == True)  # noqa: E712
                .values(is_group_admin=False)
            )
            await session.execute(
                sa_delete(DepartmentAdminGrant).where(DepartmentAdminGrant.user_id != plan.admin_id)
            )
            await session.execute(
                sa_update(UserMenuAccess)
                .where(
                    UserMenuAccess.user_id != plan.admin_id,
                    UserMenuAccess.status == UserMenuAccessStatus.ACTIVE,
                )
                .values(
                    status=UserMenuAccessStatus.REVOKED,
                    revoked_by_user_id=plan.admin_id,
                    revoked_at=now,
                    revoked_reason=RESET_MENU_REVOKE_REASON,
                )
            )
            await session.execute(
                sa_update(Knowledge)
                .where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
                .values(user_id=plan.admin_id)
            )

            if plan.knowledge_space_ids:
                await session.execute(
                    sa_update(KnowledgeFile)
                    .where(KnowledgeFile.knowledge_id.in_(list(plan.knowledge_space_ids)))
                    .values(
                        user_id=plan.admin_id,
                        user_name=plan.admin_user_name,
                        updater_id=plan.admin_id,
                        updater_name=plan.admin_user_name,
                    )
                )
                space_id_strings = [str(sid) for sid in plan.knowledge_space_ids]
                await session.execute(
                    sa_delete(SpaceChannelMember).where(
                        SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                        SpaceChannelMember.business_id.in_(space_id_strings),
                        SpaceChannelMember.user_id != plan.admin_id,
                    )
                )
                await session.execute(
                    sa_update(SpaceChannelMember)
                    .where(
                        SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                        SpaceChannelMember.business_id.in_(space_id_strings),
                        SpaceChannelMember.user_id == plan.admin_id,
                    )
                    .values(
                        user_role=UserRoleEnum.CREATOR,
                        relation=ChannelRelationEnum.OWNER,
                        status=MembershipStatusEnum.ACTIVE,
                        membership_source='permission_reset',
                        department_admin_promoted_from_role=None,
                        grant_subject_type=None,
                        grant_subject_id=None,
                        grant_relation=None,
                        grant_include_children=False,
                        grant_model_id=None,
                        grant_binding_key=None,
                    )
                )
                for space_id in plan.admin_member_insert_space_ids:
                    session.add(SpaceChannelMember(
                        business_id=str(space_id),
                        business_type=BusinessTypeEnum.SPACE,
                        user_id=plan.admin_id,
                        user_role=UserRoleEnum.CREATOR,
                        relation=ChannelRelationEnum.OWNER,
                        status=MembershipStatusEnum.ACTIVE,
                        membership_source='permission_reset',
                    ))
                await session.execute(
                    sa_update(KnowledgeSpaceScope)
                    .where(KnowledgeSpaceScope.space_id.in_(list(plan.knowledge_space_ids)))
                    .values(
                        level=KnowledgeSpaceLevelEnum.PERSONAL.value,
                        owner_type=KnowledgeSpaceOwnerTypeEnum.USER.value,
                        owner_id=plan.admin_id,
                        created_by=plan.admin_id,
                    )
                )
                for item in plan.scope_inserts:
                    session.add(KnowledgeSpaceScope(
                        tenant_id=item.tenant_id,
                        space_id=item.space_id,
                        level=KnowledgeSpaceLevelEnum.PERSONAL,
                        owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
                        owner_id=plan.admin_id,
                        created_by=plan.admin_id,
                    ))
                await session.execute(
                    sa_delete(DepartmentKnowledgeSpace).where(
                        DepartmentKnowledgeSpace.space_id.in_(list(plan.knowledge_space_ids))
                    )
                )

            await session.execute(
                sa_update(ShareLink)
                .where(
                    ShareLink.resource_type == ResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                    ShareLink.status == ShareLinkStatusEnum.ACTIVE,
                )
                .values(status=ShareLinkStatusEnum.INACTIVE)
            )
            await _save_relation_bindings(session, list(plan.relation_bindings_kept))
            pre_recorded_ids = await _pre_record_reset_failed_tuples(session, operations)
            if plan.failed_tuple_ids_to_invalidate:
                await session.execute(
                    sa_update(FailedTuple)
                    .where(FailedTuple.id.in_(list(plan.failed_tuple_ids_to_invalidate)))
                    .values(
                        status='dead',
                        error_message=RESET_FAILED_TUPLE_ERROR,
                    )
                )
            await session.commit()
            return pre_recorded_ids


async def _pre_record_reset_failed_tuples(
    session,
    operations: Sequence[TupleOperation],
) -> tuple[int, ...]:
    if not operations:
        return ()
    rows = [
        FailedTuple(
            action=op.action,
            fga_user=op.user,
            relation=op.relation,
            object=op.object,
            error_message='pre-recorded by admin-only knowledge permission reset',
        )
        for op in operations
    ]
    session.add_all(rows)
    await session.flush()
    return tuple(int(row.id) for row in rows if row.id is not None)


async def _mark_reset_failed_tuples_succeeded(record_ids: Sequence[int]) -> None:
    if not record_ids:
        return
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            await session.execute(
                sa_update(FailedTuple)
                .where(FailedTuple.id.in_(list(record_ids)))
                .values(status='succeeded')
            )
            await session.commit()


async def _save_relation_bindings(session, bindings: list[dict[str, Any]]) -> None:
    row = (await session.exec(
        select(Config).where(Config.key == RELATION_BINDINGS_CONFIG_KEY)
    )).first()
    if row is None:
        if bindings:
            session.add(Config(
                key=RELATION_BINDINGS_CONFIG_KEY,
                value=json.dumps(bindings, ensure_ascii=False),
            ))
        return
    row.value = json.dumps(bindings, ensure_ascii=False)
    session.add(row)


async def _invalidate_permission_caches(plan: ResetPlan) -> None:
    await PermissionCache.invalidate_all()
    try:
        from bisheng.core.cache.redis_manager import get_redis_client
        redis = await get_redis_client()
        for uid in [plan.admin_id, *plan.non_admin_user_ids]:
            await redis.adelete(f'user:{uid}:is_super')
    except Exception as exc:
        raise RuntimeError(
            'Database and OpenFGA changes were applied, but permission cache invalidation failed. '
            'Clear Redis user:*:is_super cache entries or wait for TTL before treating the reset as complete.'
        ) from exc


def print_report(plan: ResetPlan, *, apply: bool, as_json: bool) -> None:
    payload = {
        'mode': 'apply' if apply else 'dry-run',
        'admin': {
            'user_id': plan.admin_id,
            'user_name': plan.admin_user_name,
        },
        'counts': plan.counts,
        'warnings': list(plan.warnings),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print('=== Admin-only knowledge permission reset ===')
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f'Admin: user_id={plan.admin_id}, user_name={plan.admin_user_name}')
    print('')
    for key in sorted(plan.counts):
        print(f'- {key}: {plan.counts[key]}')
    if plan.warnings:
        print('')
        for warning in plan.warnings:
            print(f'[warn] {warning}')
    if not apply:
        print('')
        print('Dry-run only. Re-run with --apply to execute these changes.')


async def _amain(args: argparse.Namespace) -> int:
    try:
        plan = await collect_reset_plan(require_fga=args.apply)
        print_report(plan, apply=args.apply, as_json=args.json)
        if not args.apply:
            return 0
        await apply_reset_plan(plan)
        print('')
        print('[done] admin-only knowledge permission reset applied.')
        return 0
    except AdminResolutionError as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2
    except Exception as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 3
    finally:
        await close_app_context()
        gc.collect()
        await asyncio.sleep(0)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == '__main__':
    sys.exit(main())
