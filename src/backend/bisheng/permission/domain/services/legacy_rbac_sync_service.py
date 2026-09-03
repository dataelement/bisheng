"""Identity-only compatibility hooks retained after the F048 cutover.

Legacy RoleAccess rows no longer project business-resource tuples. The only
runtime responsibilities left here are the system-super and user-group
identity relations consumed by the F048 authorization model.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from bisheng.database.constants import AdminRole
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)


# Kept as an explicit retirement invariant for static checks and callers that
# still notify this adapter after a legacy role mutation.
ACCESS_TYPE_TO_FGA: dict[int, tuple[str, str]] = {}


class LegacyRBACSyncService:
    """Synchronize identity relations without interpreting business grants."""

    @classmethod
    async def sync_user_role_change(
        cls,
        user_id: int,
        old_role_ids: Iterable[int],
        new_role_ids: Iterable[int],
    ) -> None:
        """Mirror only the global-super identity relation."""

        old_ids = {
            int(role_id)
            for role_id in (old_role_ids or [])
            if role_id is not None
        }
        new_ids = {
            int(role_id)
            for role_id in (new_role_ids or [])
            if role_id is not None
        }
        if (AdminRole in old_ids) == (AdminRole in new_ids):
            return
        action = "write" if AdminRole in new_ids else "delete"
        await cls._write_operations(
            [
                TupleOperation(
                    action=action,
                    user=f"user:{user_id}",
                    relation="super_admin",
                    object="system:global",
                ),
            ],
            [user_id],
        )

    @classmethod
    async def sync_user_auth_created(
        cls,
        user_id: int,
        role_ids: Iterable[int],
        member_group_ids: Iterable[int] | None = None,
        admin_group_ids: Iterable[int] | None = None,
    ) -> None:
        """Initialize global-super and user-group identity tuples."""

        await cls.sync_user_role_change(user_id, [], role_ids)
        operations = [
            TupleOperation(
                action="write",
                user=f"user:{user_id}",
                relation="member",
                object=f"user_group:{group_id}",
            )
            for group_id in (member_group_ids or [])
        ]
        operations.extend(
            TupleOperation(
                action="write",
                user=f"user:{user_id}",
                relation="admin",
                object=f"user_group:{group_id}",
            )
            for group_id in (admin_group_ids or [])
        )
        await cls._write_operations(operations, [user_id])

    @staticmethod
    async def sync_role_access_change(
        role_id: int,
        access_type: int,
        old_ids: Iterable[str],
        new_ids: Iterable[str],
    ) -> None:
        """Retired compatibility callback; normalized Grants are authoritative."""

        del role_id, access_type, old_ids, new_ids

    @staticmethod
    async def sync_role_deleted(role_id: int) -> None:
        """Retired compatibility callback; deleting a role changes no Grant."""

        del role_id

    @staticmethod
    async def reconcile_user_role_access(user_id: int) -> None:
        """Retired compatibility callback; F048 migration owns reconciliation."""

        del user_id

    @classmethod
    async def cleanup_user_group_subject_tuples(cls, group_id: int) -> None:
        """Delete tuples where a removed user group is the subject."""

        from bisheng.permission.domain.services.permission_service import (
            PermissionService,
        )

        fga = await PermissionService._aget_fga()
        if fga is None:
            logger.warning(
                "FGAClient not available for user_group subject cleanup: %s",
                group_id,
            )
            return

        operations: list[TupleOperation] = []
        for relation in ("member", "admin"):
            user = f"user_group:{group_id}#{relation}"
            try:
                tuples = await fga.read_tuples(user=user)
            except Exception as exc:
                logger.warning("Failed to read tuples for %s: %s", user, exc)
                continue
            operations.extend(
                TupleOperation(
                    action="delete",
                    user=tuple_data.get("user", ""),
                    relation=tuple_data.get("relation", ""),
                    object=tuple_data.get("object", ""),
                )
                for tuple_data in (tuples or [])
            )
        await cls._write_operations(operations, [])

    @classmethod
    async def _write_operations(
        cls,
        operations: list[TupleOperation],
        affected_user_ids: Iterable[int],
    ) -> None:
        if not operations:
            return
        from bisheng.permission.domain.services.permission_service import (
            PermissionService,
        )

        await PermissionService.batch_write_tuples(operations, crash_safe=True)
        await cls._invalidate_user_caches(affected_user_ids)

    @staticmethod
    async def _invalidate_user_caches(
        affected_user_ids: Iterable[int],
    ) -> None:
        from bisheng.permission.domain.services.permission_cache import (
            PermissionCache,
        )

        for user_id in sorted({int(value) for value in affected_user_ids}):
            await PermissionCache.invalidate_user(user_id)
            try:
                from bisheng.core.cache.redis_manager import get_redis_client

                redis = await get_redis_client()
                await redis.adelete(f"user:{user_id}:is_super")
            except Exception:
                logger.debug(
                    "Could not clear cached global-super marker for user %s",
                    user_id,
                )
