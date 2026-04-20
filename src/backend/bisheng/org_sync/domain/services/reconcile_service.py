"""F015 OrgReconcileService — 6h forced-reconcile orchestration.

Drives one reconcile run for a single ``org_sync_config`` row:

  1. Load the config; skip the F014 SSO-realtime seed (provider='sso_realtime').
  2. Acquire Redis SETNX lock ``org_reconcile:{config_id}`` (AC-13 / INV-T12 atomicity).
  3. Instantiate the provider + fetch the remote department tree.
  4. Load the local active-department snapshot for the config's tenant.
  5. Diff via :class:`RemoteDeptDiffer` — each op carries ``incoming_ts``.
  6. Upsert loop: per-op OrgSyncTsGuard → APPLY/SKIP_TS.
  7. Archive loop: per-op guard → APPLY/SKIP_TS; on APPLY, detect the
     same-ts upsert-vs-remove collision and, if detected, write the
     ``ts_conflict`` event row + audit_log.action='dept.sync_conflict'
     (AC-11 "remove wins").
  8. Cross-tenant moves → UserTenantSyncService.sync_user per primary
     member so JWT ``tenant_id`` + ``token_version`` refresh (INV-T2).
  9. Batch-summary ``OrgSyncLog`` flush via :func:`flush_log`.
 10. Event rows (stale_ts / ts_conflict) persisted via
     :meth:`OrgSyncLogDao.acreate_event`.
 11. Return :class:`ReconcileResult` for caller telemetry.

The service touches every F011/F012/F013/F014 component but owns no
mutation logic on its own — all writes delegate to existing DAOs.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    SsoReconcileLockBusyError,
    SsoSameTsRemoveAppliedWarnError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import (
    DepartmentDao,
    UserDepartmentDao,
)
from bisheng.org_sync.domain.models.org_sync import (
    OrgSyncConfigDao,
    OrgSyncLogDao,
    decrypt_auth_config,
)
from bisheng.org_sync.domain.providers.base import get_provider
from bisheng.org_sync.domain.services.remote_dept_differ import (
    ArchiveOp,
    MoveOp,
    ReconcileDiff,
    RemoteDeptDiffer,
    UpsertOp,
)
from bisheng.org_sync.domain.services.ts_guard import (
    GuardDecision,
    OrgSyncTsGuard,
)
from bisheng.sso_sync.domain.schemas.payloads import DepartmentUpsertItem
from bisheng.sso_sync.domain.services.dept_upsert_service import (
    DeptUpsertService,
)
from bisheng.sso_sync.domain.services.org_sync_log_writer import (
    OrgSyncLogBuffer,
    flush_log,
)
from bisheng.tenant.domain.constants import (
    DeletionSource,
    UserTenantSyncTrigger,
)
from bisheng.tenant.domain.services.department_deletion_handler import (
    DepartmentDeletionHandler,
)
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


@dataclass
class ReconcileResult:
    """Run summary surfaced back to the Celery entrypoint.

    Attributes mirror ``event_rows`` counters so the fan-out beat can
    log per-config numbers without re-reading the DB.
    """

    skipped: bool = False
    skip_reason: Optional[str] = None
    applied_upsert: int = 0
    applied_archive: int = 0
    cross_tenant_moves: int = 0
    user_syncs_triggered: int = 0
    skipped_ts: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OrgReconcileService:
    """Pure-orchestration service; every mutation delegates to an existing DAO."""

    # The F014 seed id=9999 is reserved for HMAC realtime logs — never
    # fed through provider.fetch_departments.
    SKIP_PROVIDER = 'sso_realtime'

    @classmethod
    async def reconcile_config(cls, config_id: int) -> ReconcileResult:
        config = await OrgSyncConfigDao.aget_by_id(config_id)
        if config is None:
            return ReconcileResult(skipped=True, skip_reason='config_not_found')
        if config.provider == cls.SKIP_PROVIDER:
            return ReconcileResult(
                skipped=True, skip_reason='sso_realtime_seed')
        if config.status != 'active':
            return ReconcileResult(
                skipped=True, skip_reason=f'status={config.status}')

        # Celery task entrypoint has no HTTP middleware, so set the
        # tenant context ourselves — F011/F014 pattern: do the DB-touching
        # work under ROOT_TENANT_ID + bypass_tenant_filter so SQLAlchemy's
        # tenant_filter event treats this as a cross-tenant maintenance
        # scan (INV-T12 reconcile inspects every dept regardless of leaf).
        async with cls._acquire_lock(config.id):
            with bypass_tenant_filter():
                tok = set_current_tenant_id(config.tenant_id or 1)
                try:
                    return await cls._run(config)
                finally:
                    current_tenant_id.reset(tok)

    # ------------------------------------------------------------------
    # Inner run (lock already held)
    # ------------------------------------------------------------------

    @classmethod
    async def _run(cls, config) -> ReconcileResult:
        result = ReconcileResult()

        provider = cls._build_provider(config)
        try:
            await provider.authenticate()
        except Exception as e:  # Provider auth failure — nothing to diff.
            logger.exception(f'reconcile auth failed for config {config.id}')
            result.errors.append(f'authenticate: {e!s}')
            return result

        try:
            scope_roots = (config.sync_scope or {}).get('root_dept_ids') or None
            remote = await provider.fetch_departments(scope_roots)
        except Exception as e:
            logger.exception(f'fetch_departments failed for config {config.id}')
            result.errors.append(f'fetch_departments: {e!s}')
            return result

        local = await DepartmentDao.aget_active_by_tenant(config.tenant_id)

        now_ts = int(time.time())
        diff = RemoteDeptDiffer.diff(
            remote_depts=remote, local_depts=local,
            source=config.provider, ts=now_ts,
        )

        buffer = OrgSyncLogBuffer()
        event_rows: list[dict] = []

        # --- Upserts -------------------------------------------------------
        for op in diff.upserts:
            await cls._apply_upsert(
                op, config=config, buffer=buffer,
                event_rows=event_rows, result=result,
            )

        # --- Archives ------------------------------------------------------
        for op in diff.archives:
            await cls._apply_archive(
                op, config=config, buffer=buffer,
                event_rows=event_rows, result=result,
            )

        # --- Cross-tenant moves -------------------------------------------
        for mv in diff.moves:
            await cls._apply_move(
                mv, buffer=buffer, result=result,
            )

        # --- Flush batch summary + event rows -----------------------------
        try:
            await flush_log(
                buffer, trigger_type='reconcile', config_id=config.id,
            )
        except Exception as e:
            logger.exception(f'flush_log failed for config {config.id}')
            result.errors.append(f'flush_log: {e!s}')

        for ev in event_rows:
            try:
                await OrgSyncLogDao.acreate_event(
                    event_type=ev['event_type'], level=ev['level'],
                    external_id=ev.get('external_id'),
                    source_ts=ev.get('source_ts'),
                    config_id=config.id,
                    tenant_id=config.tenant_id,
                    error_details=ev.get('error_details'),
                )
            except Exception as e:  # per-row resilience
                logger.exception(
                    f'event_row persist failed for config {config.id}: {e}')
                result.errors.append(f'event_row: {e!s}')

        return result

    # ------------------------------------------------------------------
    # Per-op helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _apply_upsert(
        cls,
        op: UpsertOp,
        *,
        config,
        buffer: OrgSyncLogBuffer,
        event_rows: list[dict],
        result: ReconcileResult,
    ) -> None:
        try:
            existing = await DepartmentDao.aget_by_source_external_id(
                source=config.provider, external_id=op.external_id,
            )
            decision = await OrgSyncTsGuard.check_and_update(
                existing, op.incoming_ts, 'upsert',
            )
            if decision == GuardDecision.SKIP_TS:
                event_rows.append(dict(
                    event_type='stale_ts', level='warn',
                    external_id=op.external_id, source_ts=op.incoming_ts,
                    error_details={
                        'action': 'upsert',
                        'last_sync_ts': int(getattr(existing, 'last_sync_ts', 0) or 0) if existing else 0,
                    },
                ))
                buffer.warn(
                    'stale_ts', op.external_id,
                    incoming_ts=op.incoming_ts,
                    last_ts=int(getattr(existing, 'last_sync_ts', 0) or 0) if existing else 0,
                )
                result.skipped_ts += 1
                return

            item = DepartmentUpsertItem(
                external_id=op.external_id,
                name=op.name,
                parent_external_id=op.parent_external_id,
                sort=op.sort_order,
                ts=op.incoming_ts,
            )
            await DeptUpsertService.upsert_from_sync_payload(
                existing=existing, item=item,
                source=config.provider, last_sync_ts=op.incoming_ts,
            )
            # OrgSyncLogBuffer exposes raw counters + warn/error only;
            # dept_created vs dept_updated mirrors F009 batch-summary
            # semantics so the management UI's history pane shows the
            # expected totals.
            if op.is_new:
                buffer.dept_created += 1
            else:
                buffer.dept_updated += 1
            result.applied_upsert += 1
        except Exception as e:
            logger.exception(
                f'upsert failed for {op.external_id} (config {config.id}): {e}')
            buffer.error('upsert', op.external_id, str(e))
            result.errors.append(f'upsert {op.external_id}: {e!s}')

    @classmethod
    async def _apply_archive(
        cls,
        op: ArchiveOp,
        *,
        config,
        buffer: OrgSyncLogBuffer,
        event_rows: list[dict],
        result: ReconcileResult,
    ) -> None:
        try:
            existing = await DepartmentDao.aget_by_source_external_id(
                source=config.provider, external_id=op.external_id,
            )
            if existing is None:
                return

            decision = await OrgSyncTsGuard.check_and_update(
                existing, op.incoming_ts, 'remove',
            )
            if decision == GuardDecision.SKIP_TS:
                event_rows.append(dict(
                    event_type='stale_ts', level='warn',
                    external_id=op.external_id, source_ts=op.incoming_ts,
                    error_details={
                        'action': 'remove',
                        'last_sync_ts': int(getattr(existing, 'last_sync_ts', 0) or 0),
                    },
                ))
                buffer.warn(
                    'stale_ts', op.external_id,
                    incoming_ts=op.incoming_ts,
                    last_ts=int(getattr(existing, 'last_sync_ts', 0) or 0),
                )
                result.skipped_ts += 1
                return

            # AC-11: detect Gateway-upsert-followed-by-Celery-remove at
            # identical ts. TsGuard APPLIES this remove; our job is to
            # mark it as a conflict + write audit + event row so admins
            # can investigate.
            is_same_ts_conflict = (
                int(getattr(existing, 'last_sync_ts', 0) or 0) == op.incoming_ts
                and int(getattr(existing, 'is_deleted', 0) or 0) == 0
            )

            if is_same_ts_conflict:
                event_rows.append(dict(
                    event_type='ts_conflict', level='warn',
                    external_id=op.external_id, source_ts=op.incoming_ts,
                    error_details={
                        'resolution': 'remove_wins',
                        'via': 'celery_reconcile',
                    },
                ))
                try:
                    await AuditLogDao.ainsert_v2(
                        tenant_id=config.tenant_id, operator_id=0,
                        operator_tenant_id=config.tenant_id,
                        action='dept.sync_conflict',
                        target_type='department',
                        target_id=str(existing.id),
                        metadata={
                            'external_id': op.external_id,
                            'source_ts': op.incoming_ts,
                            'resolution': 'remove_wins',
                            'via': 'celery_reconcile',
                        },
                        ip_address='internal',
                    )
                except Exception as e:  # audit failure must not abort the op
                    logger.exception(
                        f'audit_log.ainsert_v2 failed for {op.external_id}: {e}')
                    result.errors.append(f'audit {op.external_id}: {e!s}')
                # Error class is documented but not raised — admins watch
                # event rows + audit_log instead of HTTP surface.
                logger.warning(
                    f'{SsoSameTsRemoveAppliedWarnError.Code} '
                    f'{SsoSameTsRemoveAppliedWarnError.Msg}: {op.external_id}'
                )
                result.conflicts += 1

            await DepartmentDao.aarchive_by_external_id(
                source=config.provider, external_id=op.external_id,
                last_sync_ts=op.incoming_ts,
            )
            try:
                await DepartmentDeletionHandler.on_deleted(
                    existing.id, DeletionSource.CELERY_RECONCILE,
                )
            except Exception as e:
                logger.exception(
                    f'DepartmentDeletionHandler.on_deleted failed '
                    f'for dept {existing.id}: {e}')
                result.errors.append(
                    f'on_deleted {existing.id}: {e!s}')

            buffer.dept_archived += 1
            result.applied_archive += 1
        except Exception as e:
            logger.exception(
                f'archive failed for {op.external_id} (config {config.id}): {e}')
            buffer.error('archive', op.external_id, str(e))
            result.errors.append(f'archive {op.external_id}: {e!s}')

    @classmethod
    async def _apply_move(
        cls,
        mv: MoveOp,
        *,
        buffer: OrgSyncLogBuffer,
        result: ReconcileResult,
    ) -> None:
        if not mv.crosses_tenant:
            return
        result.cross_tenant_moves += 1
        try:
            user_ids = await UserDepartmentDao.aget_user_ids_by_department(
                mv.dept_id, is_primary=True,
            )
        except Exception as e:
            logger.exception(
                f'aget_user_ids_by_department failed for {mv.dept_id}: {e}')
            result.errors.append(f'move_fetch {mv.dept_id}: {e!s}')
            return

        for uid in user_ids:
            try:
                await UserTenantSyncService.sync_user(
                    uid, trigger=UserTenantSyncTrigger.CELERY_RECONCILE,
                )
                result.user_syncs_triggered += 1
            except Exception as e:
                logger.exception(
                    f'UserTenantSyncService.sync_user({uid}) failed: {e}')
                buffer.error('sync_user', str(uid), str(e))
                result.errors.append(f'sync_user {uid}: {e!s}')

    # ------------------------------------------------------------------
    # Redis SETNX lock (AC-13)
    # ------------------------------------------------------------------

    @classmethod
    @asynccontextmanager
    async def _acquire_lock(cls, config_id: int):
        """Per-config reconcile lock.

        Raises :class:`SsoReconcileLockBusyError` without running the body
        if another worker is already inside ``_run`` for the same config
        (AC-13). TTL matches the Celery hard time limit to guarantee the
        lock can never outlive a stuck worker.
        """
        redis = await get_redis_client()
        key = f'org_reconcile:{config_id}'
        ex = settings.reconcile.redis_lock_ttl_seconds
        ok = await redis.async_connection.set(
            key, b'1', nx=True, ex=ex,
        )
        if not ok:
            raise SsoReconcileLockBusyError.http_exception()
        try:
            yield
        finally:
            try:
                await redis.async_connection.delete(key)
            except Exception:
                logger.exception(
                    f'failed to release reconcile lock {key}; TTL fallback')

    # ------------------------------------------------------------------
    # Provider wiring
    # ------------------------------------------------------------------

    @classmethod
    def _build_provider(cls, config):
        """Decrypt ``auth_config`` and instantiate the provider by name."""
        try:
            auth_dict = decrypt_auth_config(config.auth_config)
        except Exception as e:
            logger.exception(
                f'decrypt_auth_config failed for config {config.id}: {e}')
            auth_dict = {}
        return get_provider(config.provider, auth_dict)
