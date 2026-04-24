"""Legacy RBAC compatibility sync for OpenFGA.

The v2.5 migration keeps ``roleaccess`` / ``userrole`` and legacy user-group
APIs for compatibility, but ReBAC checks read OpenFGA.  Any post-migration
change to those legacy tables must therefore emit matching tuple changes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.sql import bindparam

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)


ACCESS_TYPE_TO_FGA: dict[int, tuple[str, str]] = {
    1: ('knowledge_library', 'viewer'),
    3: ('knowledge_library', 'editor'),
    5: ('assistant', 'viewer'),
    6: ('assistant', 'editor'),
    7: ('tool', 'viewer'),
    8: ('tool', 'editor'),
    9: ('workflow', 'viewer'),
    10: ('workflow', 'editor'),
    11: ('dashboard', 'viewer'),
    12: ('dashboard', 'editor'),
}

GROUP_RESOURCE_TYPE_TO_FGA: dict[int, tuple[str, ...]] = {
    1: ('knowledge_library', 'knowledge_space'),
    3: ('assistant',),
    4: ('tool',),
    5: ('workflow',),
    6: ('dashboard',),
}

RELATION_PRIORITY = {
    'viewer': 1,
    'editor': 2,
}

ROLE_ACCESS_RELATIONS = frozenset({'viewer', 'editor'})
ROLE_ACCESS_OBJECT_TYPES = frozenset(
    candidate_type
    for object_type, _relation in ACCESS_TYPE_TO_FGA.values()
    for candidate_type in (
        (object_type, 'knowledge_space')
        if object_type == 'knowledge_library'
        else (object_type,)
    )
)
_RELATION_BINDINGS_CONFIG_KEY = 'permission_relation_model_bindings_v1'


@dataclass(frozen=True)
class RoleAccessSignature:
    user: str
    relation: str
    object_type: str
    resource_id: str

    @property
    def user_id(self) -> Optional[int]:
        if not self.user.startswith('user:'):
            return None
        try:
            return int(self.user.split(':', 1)[1])
        except Exception:
            return None

    def to_operation(self, action: str) -> TupleOperation:
        return TupleOperation(
            action=action,
            user=self.user,
            relation=self.relation,
            object=f'{self.object_type}:{self.resource_id}',
        )


class LegacyRBACSyncService:
    """Keep legacy RBAC rows and OpenFGA tuples consistent."""

    @classmethod
    async def sync_user_role_change(
        cls,
        user_id: int,
        old_role_ids: Iterable[int],
        new_role_ids: Iterable[int],
    ) -> None:
        """Sync FGA after a user's role list changes."""
        raw_old_role_ids = {int(role_id) for role_id in (old_role_ids or []) if role_id is not None}
        raw_new_role_ids = {int(role_id) for role_id in (new_role_ids or []) if role_id is not None}

        if (AdminRole in raw_old_role_ids) != (AdminRole in raw_new_role_ids):
            action = 'write' if AdminRole in raw_new_role_ids else 'delete'
            await cls._write_operations([
                TupleOperation(
                    action=action,
                    user=f'user:{user_id}',
                    relation='super_admin',
                    object='system:global',
                ),
            ], [user_id])

        old_role_ids = cls._clean_role_ids(raw_old_role_ids)
        new_role_ids = cls._clean_role_ids(raw_new_role_ids)
        if old_role_ids == new_role_ids:
            return

        before = await cls._role_access_signatures_for_roles(user_id, old_role_ids)
        after = await cls._role_access_signatures_for_roles(user_id, new_role_ids)
        await cls._apply_signature_diff(before, after)

    @classmethod
    async def sync_user_auth_created(
        cls,
        user_id: int,
        role_ids: Iterable[int],
        member_group_ids: Iterable[int] | None = None,
        admin_group_ids: Iterable[int] | None = None,
    ) -> None:
        """Sync FGA for direct legacy user creation helpers."""
        await cls.sync_user_role_change(user_id, [], role_ids)

        operations: list[TupleOperation] = []
        for group_id in member_group_ids or []:
            operations.append(TupleOperation(
                action='write',
                user=f'user:{user_id}',
                relation='member',
                object=f'user_group:{group_id}',
            ))
        for group_id in admin_group_ids or []:
            operations.append(TupleOperation(
                action='write',
                user=f'user:{user_id}',
                relation='admin',
                object=f'user_group:{group_id}',
            ))
        await cls._write_operations(operations, [user_id])

    @classmethod
    async def sync_role_access_change(
        cls,
        role_id: int,
        access_type: int,
        old_ids: Iterable[str],
        new_ids: Iterable[str],
    ) -> None:
        """Sync FGA after one role's resource access list changes."""
        if int(role_id) == AdminRole:
            return
        if int(access_type) not in ACCESS_TYPE_TO_FGA:
            return

        old_ids = {str(x) for x in old_ids}
        new_ids = {str(x) for x in new_ids}
        if old_ids == new_ids:
            return

        user_ids = await cls._user_ids_for_role(role_id)
        if not user_ids:
            return

        for user_id in user_ids:
            current_role_ids = await cls._role_ids_for_user(user_id)
            before = await cls._role_access_signatures_for_roles(
                user_id,
                current_role_ids,
                override=(role_id, int(access_type), old_ids),
            )
            after = await cls._role_access_signatures_for_roles(
                user_id,
                current_role_ids,
            )
            await cls._apply_signature_diff(before, after)

    @classmethod
    async def sync_role_deleted(cls, role_id: int) -> None:
        """Remove FGA tuples that were derived from a deleted legacy role."""
        if int(role_id) == AdminRole:
            return
        user_ids = await cls._user_ids_for_role(role_id)
        if not user_ids:
            return
        for user_id in user_ids:
            current_role_ids = await cls._role_ids_for_user(user_id)
            before = await cls._role_access_signatures_for_roles(user_id, current_role_ids)
            after = await cls._role_access_signatures_for_roles(
                user_id,
                current_role_ids - {int(role_id)},
            )
            await cls._apply_signature_diff(before, after)

    @classmethod
    async def reconcile_user_role_access(cls, user_id: int) -> None:
        """Repair one user's current role_access-derived FGA tuples."""
        current_role_ids = await cls._role_ids_for_user(user_id)
        desired = await cls._role_access_signatures_for_roles(user_id, current_role_ids)
        actual = await cls._actual_user_role_access_signatures(user_id)

        if actual is None:
            await cls._write_operations([sig.to_operation('write') for sig in desired], [user_id])
            return

        await cls._apply_signature_diff(actual, desired)

    @classmethod
    async def sync_group_resource_move(
        cls,
        old_group_id: int,
        new_group_id: int,
        resource_type: int,
        resource_id: str,
    ) -> None:
        """Move legacy groupresource manager tuples between group admins."""
        object_types = GROUP_RESOURCE_TYPE_TO_FGA.get(int(resource_type), ())
        if not object_types:
            return
        operations: list[TupleOperation] = []
        for object_type in object_types:
            operations.append(TupleOperation(
                action='delete',
                user=f'user_group:{old_group_id}#admin',
                relation='manager',
                object=f'{object_type}:{resource_id}',
            ))
            operations.append(TupleOperation(
                action='write',
                user=f'user_group:{new_group_id}#admin',
                relation='manager',
                object=f'{object_type}:{resource_id}',
            ))
        await cls._write_operations(operations, [])

    @classmethod
    async def cleanup_user_group_subject_tuples(cls, group_id: int) -> None:
        """Delete resource tuples where the deleted user group is the subject."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        fga = PermissionService._get_fga()
        if fga is None:
            logger.warning('FGAClient not available for user_group subject cleanup: %s', group_id)
            return

        operations: list[TupleOperation] = []
        for relation in ('member', 'admin'):
            user = f'user_group:{group_id}#{relation}'
            try:
                tuples = await fga.read_tuples(user=user)
            except Exception as exc:
                logger.warning('Failed to read tuples for %s: %s', user, exc)
                continue
            for t in tuples or []:
                operations.append(TupleOperation(
                    action='delete',
                    user=t.get('user', ''),
                    relation=t.get('relation', ''),
                    object=t.get('object', ''),
                ))
        await cls._write_operations(operations, [])

    @classmethod
    async def _apply_signature_diff(
        cls,
        before: set[RoleAccessSignature],
        after: set[RoleAccessSignature],
    ) -> None:
        to_write = after - before
        stale = before - after
        protected = await cls._resource_permission_user_binding_set(stale) if stale else set()
        to_delete = stale - protected

        operations = [
            sig.to_operation('delete')
            for sig in to_delete
        ] + [
            sig.to_operation('write')
            for sig in to_write
        ]
        affected = {
            uid
            for sig in (to_delete | to_write)
            if (uid := sig.user_id) is not None
        }
        await cls._write_operations(operations, affected)

    @classmethod
    async def _write_operations(
        cls,
        operations: list[TupleOperation],
        affected_user_ids: Iterable[int],
    ) -> None:
        if not operations:
            return
        from bisheng.permission.domain.services.permission_service import PermissionService

        await PermissionService.batch_write_tuples(operations, crash_safe=True)
        await cls._invalidate_user_caches(affected_user_ids)

    @staticmethod
    async def _invalidate_user_caches(affected_user_ids: Iterable[int]) -> None:
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        for uid in sorted({int(x) for x in affected_user_ids}):
            await PermissionCache.invalidate_user(uid)
            try:
                from bisheng.core.cache.redis_manager import get_redis_client
                redis = await get_redis_client()
                await redis.adelete(f'user:{uid}:is_super')
            except Exception:
                pass

    @classmethod
    async def _role_access_signatures_for_roles(
        cls,
        user_id: int,
        role_ids: Iterable[int],
        override: Optional[tuple[int, int, set[str]]] = None,
    ) -> set[RoleAccessSignature]:
        role_ids = cls._clean_role_ids(role_ids)
        if not role_ids:
            return set()

        override_role_id = override_access_type = None
        override_ids: set[str] = set()
        if override:
            override_role_id, override_access_type, override_ids = override

        rows = await cls._role_access_rows(role_ids)
        signatures: list[RoleAccessSignature] = []
        for role_id, third_id, access_type in rows:
            if (
                override_role_id is not None
                and int(role_id) == int(override_role_id)
                and int(access_type) == int(override_access_type)
            ):
                continue
            signatures.extend(
                cls._signatures_for_access(user_id, int(access_type), str(third_id)),
            )

        if override_role_id is not None and int(override_role_id) in role_ids:
            for resource_id in override_ids:
                signatures.extend(
                    cls._signatures_for_access(user_id, int(override_access_type), resource_id),
                )

        return cls._dedupe_signatures(signatures)

    @classmethod
    def _signatures_for_access(
        cls,
        user_id: int,
        access_type: int,
        resource_id: str,
    ) -> list[RoleAccessSignature]:
        mapping = ACCESS_TYPE_TO_FGA.get(int(access_type))
        if not mapping:
            return []
        object_type, relation = mapping
        return [
            RoleAccessSignature(
                user=f'user:{user_id}',
                relation=relation,
                object_type=fga_type,
                resource_id=str(resource_id),
            )
            for fga_type in cls._fga_object_types(object_type)
        ]

    @classmethod
    def _dedupe_signatures(
        cls,
        signatures: Iterable[RoleAccessSignature],
    ) -> set[RoleAccessSignature]:
        best: dict[tuple[str, str, str], RoleAccessSignature] = {}
        for sig in signatures:
            key = (sig.user, sig.object_type, sig.resource_id)
            previous = best.get(key)
            if previous is None:
                best[key] = sig
                continue
            if RELATION_PRIORITY.get(sig.relation, 0) > RELATION_PRIORITY.get(previous.relation, 0):
                best[key] = sig
        return set(best.values())

    @staticmethod
    def _fga_object_types(object_type: str) -> tuple[str, ...]:
        if object_type == 'knowledge_library':
            return 'knowledge_library', 'knowledge_space'
        if object_type == 'knowledge_space':
            return 'knowledge_space', 'knowledge_library'
        return (object_type,)

    @staticmethod
    def _clean_role_ids(role_ids: Iterable[int]) -> set[int]:
        return {
            int(role_id)
            for role_id in (role_ids or [])
            if role_id is not None and int(role_id) != AdminRole
        }

    @classmethod
    async def _role_access_rows(
        cls,
        role_ids: set[int],
    ) -> list[tuple[int, str, int]]:
        if not role_ids:
            return []
        statement = (
            sa_text('SELECT role_id, third_id, type FROM roleaccess '
                    'WHERE role_id IN :role_ids AND type IN :access_types')
            .bindparams(bindparam('role_ids', expanding=True))
            .bindparams(bindparam('access_types', expanding=True))
        )
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                rows = (await session.execute(
                    statement,
                    {
                        'role_ids': sorted(role_ids),
                        'access_types': sorted(ACCESS_TYPE_TO_FGA.keys()),
                    },
                )).all()
        return [(int(row[0]), str(row[1]), int(row[2])) for row in rows]

    @classmethod
    async def _role_ids_for_user(cls, user_id: int) -> set[int]:
        statement = sa_text('SELECT role_id FROM userrole WHERE user_id = :user_id AND role_id != :admin_rid')
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                rows = (await session.execute(
                    statement,
                    {'user_id': int(user_id), 'admin_rid': AdminRole},
                )).all()
        return {int(row[0]) for row in rows}

    @classmethod
    async def _user_ids_for_role(cls, role_id: int) -> list[int]:
        statement = sa_text('SELECT DISTINCT user_id FROM userrole WHERE role_id = :role_id')
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                rows = (await session.execute(statement, {'role_id': int(role_id)})).all()
        return [int(row[0]) for row in rows]

    @classmethod
    async def _actual_user_role_access_signatures(
        cls,
        user_id: int,
    ) -> Optional[set[RoleAccessSignature]]:
        from bisheng.permission.domain.services.permission_service import PermissionService

        fga = PermissionService._get_fga()
        if fga is None:
            return None
        try:
            tuples = await fga.read_tuples(user=f'user:{user_id}')
        except Exception as exc:
            logger.warning('Failed to read FGA tuples for user %s: %s', user_id, exc)
            return None

        actual: set[RoleAccessSignature] = set()
        for t in tuples or []:
            user = t.get('user', '')
            relation = t.get('relation', '')
            obj = t.get('object', '')
            if relation not in ROLE_ACCESS_RELATIONS:
                continue
            parts = obj.split(':', 1)
            if len(parts) != 2:
                continue
            object_type, resource_id = parts
            if object_type not in ROLE_ACCESS_OBJECT_TYPES:
                continue
            actual.add(RoleAccessSignature(
                user=user,
                relation=relation,
                object_type=object_type,
                resource_id=resource_id,
            ))
        return actual

    @classmethod
    async def _resource_permission_user_binding_set(
        cls,
        candidates: Iterable[RoleAccessSignature],
    ) -> set[RoleAccessSignature]:
        candidates = set(candidates)
        if not candidates:
            return set()
        bindings = await cls._resource_permission_bindings()
        if not bindings:
            return set()

        protected: set[RoleAccessSignature] = set()
        for sig in candidates:
            uid = sig.user_id
            if uid is None:
                continue
            if cls._has_resource_permission_user_binding(sig, uid, bindings):
                protected.add(sig)
        return protected

    @staticmethod
    async def _resource_permission_bindings() -> list[dict]:
        from bisheng.common.models.config import ConfigDao

        row = await ConfigDao.aget_config_by_key(_RELATION_BINDINGS_CONFIG_KEY)
        if not row or not (row.value or '').strip():
            return []
        try:
            bindings = json.loads(row.value or '[]')
        except Exception:
            logger.warning('Failed to parse resource permission bindings config')
            return []
        if not isinstance(bindings, list):
            return []
        return [binding for binding in bindings if isinstance(binding, dict)]

    @classmethod
    def _has_resource_permission_user_binding(
        cls,
        sig: RoleAccessSignature,
        user_id: int,
        bindings: list[dict],
    ) -> bool:
        check_types = set(cls._fga_object_types(sig.object_type))
        return any(
            binding.get('resource_type') in check_types
            and str(binding.get('resource_id')) == sig.resource_id
            and binding.get('subject_type') == 'user'
            and str(binding.get('subject_id')) == str(user_id)
            and binding.get('relation') == sig.relation
            for binding in bindings
        )
