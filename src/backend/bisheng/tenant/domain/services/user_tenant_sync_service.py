"""UserTenantSyncService — propagate primary-department changes to leaf tenant.

v2.5.1 F012 spec §5.2. Invoked from three call sites:
  1. Successful login (auth flow) — ensures JWT carries the freshest leaf.
  2. ``UserDepartmentService.change_primary_department`` — transactional.
  3. 6h Celery reconcile (``worker/tenant_reconcile/tasks.py``) — catchup
     for cases where the other two paths were skipped (legacy code, bugs).

Behaviour:
  - Resolve the new leaf via ``TenantResolver.resolve_user_leaf_tenant``.
  - If the new leaf equals the current active leaf → no-op.
  - If the user owns resources under the OLD leaf and
    ``settings.user_tenant_sync.enforce_transfer_before_relocate`` is True,
    raise ``TenantRelocateBlockedError`` and write a blocked audit event
    (PRD Review P0-C — resources stay put, transfer first).
  - Otherwise: swap the active ``user_tenant`` row, bump
    ``user.token_version``, rewrite ``tenant:{X}#member`` FGA tuples
    (crash-safe), invalidate Redis caches, write the relocated audit
    event, and, if resources remain with the old tenant, notify the
    operator/admins via inbox.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from bisheng.common.errcode.tenant_resolver import TenantRelocateBlockedError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.tenant import (
    ROOT_TENANT_ID,
    Tenant,
    UserTenantDao,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.tenant.domain.constants import (
    TenantAuditAction,
    UserTenantSyncTrigger,
)
from bisheng.tenant.domain.services.tenant_resolver import TenantResolver
from bisheng.user.domain.models.user import UserDao

logger = logging.getLogger(__name__)


# Resource tables whose rows carry the ``tenant_id`` + owner-column pair
# we count against to decide blocked vs allowed relocation. Kept in lockstep
# with F011's `migrate-from-root` whitelist (assistant/channel/t_gpts_tools
# use ``user_id`` as creator column too; verified 2026-04-19 against their
# ORM in ``bisheng.database.models``). Tables that are missing in the
# current DB (e.g. SQLite test env) are silently skipped in
# ``_count_owned_resources``, so adding a table here does not break tests.
_OWNED_RESOURCE_TABLES: tuple[tuple[str, str], ...] = (
    ('knowledge', 'user_id'),
    ('flow', 'user_id'),
    ('assistant', 'user_id'),
    ('channel', 'user_id'),
    ('t_gpts_tools', 'user_id'),
)


class UserTenantSyncService:
    """Stateless service — classmethods only. No instance state."""

    # --- Public API -----------------------------------------------------

    @classmethod
    async def sync_user(
        cls,
        user_id: int,
        *,
        trigger: str | UserTenantSyncTrigger = UserTenantSyncTrigger.MANUAL,
    ) -> Tenant:
        """Align ``user_tenant`` + JWT token_version with the resolved leaf.

        Returns the authoritative leaf Tenant. Raises
        ``TenantRelocateBlockedError`` only when the configuration flag
        demands it *and* the user owns resources under the old tenant.
        """
        trigger_value = cls._trigger_str(trigger)

        new_leaf = await TenantResolver.resolve_user_leaf_tenant(user_id)
        current = await UserTenantDao.aget_active_user_tenant(user_id)

        if current is not None and current.tenant_id == new_leaf.id:
            return new_leaf  # No change — cheap exit.

        old_tenant_id: Optional[int] = (
            current.tenant_id if current is not None else None
        )

        owned_count = 0
        if old_tenant_id is not None:
            owned_count = await cls._count_owned_resources(user_id, old_tenant_id)

        if owned_count > 0 and cls._enforce_transfer_before_relocate():
            await cls._write_relocation_audit(
                user_id=user_id,
                action=TenantAuditAction.USER_TENANT_RELOCATE_BLOCKED,
                audit_tenant_id=old_tenant_id or ROOT_TENANT_ID,
                old_tenant_id=old_tenant_id,
                new_tenant_id=new_leaf.id,
                owned_count=owned_count,
                trigger=trigger_value,
            )
            raise TenantRelocateBlockedError(
                owned_count=owned_count,
                old_tenant_id=old_tenant_id,
                new_tenant_id=new_leaf.id,
            )

        # Perform the swap.
        await UserTenantDao.aactivate_user_tenant(user_id, new_leaf.id)
        await UserDao.aincrement_token_version(user_id)
        await cls._rewrite_fga_member_tuples(
            user_id, old_tenant_id, new_leaf.id,
        )
        await cls._invalidate_redis_caches(user_id)
        # F019 AC-11: once ``token_version`` has been bumped the old JWT is
        # dead, so any admin-scope the user had set under that JWT must die
        # with it. Best-effort — a scope DEL failure does not block the
        # relocation (audit_log already records the swap). Local import
        # keeps tenant → admin module dependency off the top-level graph.
        try:
            from bisheng.admin.domain.services.tenant_scope import TenantScopeService
            await TenantScopeService.clear_on_token_version_bump(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug('admin_scope clear on relocate failed: %s', exc)

        relocate_reason = (
            'no_primary_department'
            if old_tenant_id is None and new_leaf.id == ROOT_TENANT_ID
            else None
        )
        await cls._write_relocation_audit(
            user_id=user_id,
            action=TenantAuditAction.USER_TENANT_RELOCATED,
            audit_tenant_id=new_leaf.id,
            old_tenant_id=old_tenant_id,
            new_tenant_id=new_leaf.id,
            owned_count=owned_count,
            trigger=trigger_value,
            reason=relocate_reason,
        )

        if owned_count > 0:
            # Inbox notification — best effort; audit log is the source of truth.
            await cls._notify_resource_owner_relocation(
                user_id, old_tenant_id, new_leaf.id, owned_count,
            )

        return new_leaf

    @classmethod
    async def sync_subtree_primary_users(
        cls,
        dept_path: str,
        *,
        trigger: UserTenantSyncTrigger,
    ) -> Dict[str, Any]:
        """Re-sync every primary-dept user under a department subtree.

        Used by the mount / unmount / move event handlers to make the
        ``user_tenant`` table reflect the new tree topology immediately,
        rather than waiting for each user's next login (the PRD §4.5
        "自动成为该子租户成员" semantics). The lazy login-time path stays
        as a fallback for users this batch fails on or who join later.

        Returns ``{'synced': [user_ids...], 'failed': [(user_id, err), ...]}``.
        Single-user failures are logged and collected but never propagate —
        the caller (mount/unmount/move) must not roll back its own commit
        because a downstream user-sync hiccup hit a relocate-block or FGA
        glitch.
        """
        if not dept_path:
            return {'synced': [], 'failed': []}

        dept_ids = await DepartmentDao.aget_subtree_ids(dept_path)
        if not dept_ids:
            return {'synced': [], 'failed': []}

        user_ids: set[int] = set()
        for dept_id in dept_ids:
            ids = await UserDepartmentDao.aget_user_ids_by_department(
                dept_id, is_primary=True,
            )
            user_ids.update(ids)
        if not user_ids:
            return {'synced': [], 'failed': []}

        synced: list[int] = []
        failed: list[tuple[int, str]] = []
        for uid in sorted(user_ids):
            try:
                await cls.sync_user(uid, trigger=trigger)
                synced.append(uid)
            except Exception as exc:  # noqa: BLE001
                failed.append((uid, repr(exc)))
                logger.warning(
                    'sync_subtree_primary_users: user=%s trigger=%s failed: %s',
                    uid, cls._trigger_str(trigger), exc,
                )

        if failed:
            logger.warning(
                'sync_subtree_primary_users: trigger=%s synced=%d failed=%d',
                cls._trigger_str(trigger), len(synced), len(failed),
            )
        return {'synced': synced, 'failed': failed}

    # --- Internals ------------------------------------------------------

    @staticmethod
    def _trigger_str(trigger) -> str:
        if isinstance(trigger, UserTenantSyncTrigger):
            return trigger.value
        return str(trigger)

    @staticmethod
    def _enforce_transfer_before_relocate() -> bool:
        """Read the flag lazily — tests can monkeypatch settings."""
        from bisheng.common.services.config_service import settings
        try:
            return bool(settings.user_tenant_sync.enforce_transfer_before_relocate)
        except AttributeError:
            # v2.5.0 Settings instance without the F012 section — treat as off.
            return False

    @classmethod
    async def _count_owned_resources(
        cls, user_id: int, tenant_id: int,
    ) -> int:
        """Count rows the user owns under ``tenant_id`` across the MVP
        whitelist. Uses raw parameterised SQL so each COUNT is a single
        round-trip; ``bypass_tenant_filter`` + ``strict_tenant_filter`` keep
        any SQLAlchemy event listeners from rewriting our WHERE clause.
        Missing tables (e.g. on a test DB without the full schema) are
        silently skipped.
        """
        from bisheng.core.database import get_async_db_session
        from sqlalchemy import text

        total = 0
        with bypass_tenant_filter(), strict_tenant_filter():
            async with get_async_db_session() as session:
                for table_name, user_col in _OWNED_RESOURCE_TABLES:
                    try:
                        result = await session.exec(
                            text(
                                f'SELECT COUNT(*) FROM {table_name} '
                                f'WHERE {user_col} = :uid '
                                f'AND tenant_id = :tid'
                            ),
                            params={'uid': user_id, 'tid': tenant_id},
                        )
                        row = result.first()
                        if row is not None:
                            total += int(row[0])
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            'owned-resource count skipped for %s: %s',
                            table_name, exc,
                        )
        return total

    @classmethod
    async def _rewrite_fga_member_tuples(
        cls,
        user_id: int,
        old_tenant_id: Optional[int],
        new_tenant_id: int,
    ) -> None:
        """Revoke ``tenant:{old}#member`` and grant ``tenant:{new}#member``.

        Uses ``batch_write_tuples(crash_safe=True)`` so an FGA outage
        between MySQL commit and the FGA write lands in ``failed_tuples``
        for the retry worker to pick up. This function never raises on FGA
        failure — the DB swap has priority.
        """
        operations: list[TupleOperation] = []
        if old_tenant_id is not None and old_tenant_id != new_tenant_id:
            operations.append(TupleOperation(
                action='delete',
                user=f'user:{user_id}',
                relation='member',
                object=f'tenant:{old_tenant_id}',
            ))
        # New tenant membership — skip Root since F013 doesn't write tenant:1#member
        # tuples (see INV-T3). The invariant is still enforced here because Root
        # users derive visibility from leaf == Root, not from #member.
        if new_tenant_id != ROOT_TENANT_ID:
            operations.append(TupleOperation(
                action='write',
                user=f'user:{user_id}',
                relation='member',
                object=f'tenant:{new_tenant_id}',
            ))
        if not operations:
            return
        try:
            await PermissionService.batch_write_tuples(operations, crash_safe=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'FGA tuple rewrite for user %d relocate %s→%s failed: %s',
                user_id, old_tenant_id, new_tenant_id, exc,
            )

    @classmethod
    async def _invalidate_redis_caches(cls, user_id: int) -> None:
        """Evict every per-user cache that could now be stale."""
        try:
            from bisheng.core.cache.redis_manager import get_redis_client
            redis = await get_redis_client()
        except Exception as exc:  # noqa: BLE001
            logger.debug('Redis unavailable; cache invalidation skipped: %s', exc)
            return
        for key in (
            f'user:{user_id}:leaf_tenant',
            f'user:{user_id}:token_version',
            f'user:{user_id}:is_super',
        ):
            try:
                await redis.adelete(key)
            except Exception as exc:  # noqa: BLE001
                logger.debug('Redis delete %s failed: %s', key, exc)

    @classmethod
    async def _write_relocation_audit(
        cls,
        user_id: int,
        action: TenantAuditAction,
        audit_tenant_id: int,
        old_tenant_id: Optional[int],
        new_tenant_id: int,
        owned_count: int,
        trigger: str,
        reason: Optional[str] = None,
    ) -> None:
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=audit_tenant_id,
                operator_id=user_id,
                operator_tenant_id=audit_tenant_id,
                action=action.value,
                target_type='user',
                target_id=str(user_id),
                reason=reason,
                metadata={
                    'old_tenant_id': old_tenant_id,
                    'new_tenant_id': new_tenant_id,
                    'owned_count': owned_count,
                    'trigger': trigger,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error('audit %s write failed: %s', action.value, exc)

    @classmethod
    async def _notify_resource_owner_relocation(
        cls, user_id: int,
        old_tenant_id: Optional[int], new_tenant_id: int,
        owned_count: int,
    ) -> None:
        """Best-effort inbox notice — audit_log is the source of truth."""
        from bisheng.tenant.domain.services.inbox_helper import send_inbox_notice
        title = '租户归属已变更 (tenant relocated)'
        body = (
            f'您的主部门发生变更，已从 Tenant {old_tenant_id} 切换至 '
            f'Tenant {new_tenant_id}。您名下仍有 {owned_count} 个资源保留在原 Tenant，'
            f'请联系管理员完成资源交接。'
        )
        await send_inbox_notice(title, body, recipients=[user_id])
