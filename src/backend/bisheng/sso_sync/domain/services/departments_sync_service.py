"""F014 batch department sync — ``POST /api/v1/departments/sync``.

Gateway pushes upsert + remove deltas in bulk. Each item goes through
:class:`OrgSyncTsGuard` before being applied so that the Celery
reconciliation (F015) and the realtime push converge on the same answer
when their messages collide (INV-T12).

Per-item failures are isolated: one malformed ``external_id`` cannot abort
the rest of the batch (AC-11). The response summarises the batch so the
Gateway can diff against its own local counters without resorting to
querying ``org_sync_log``.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.org_sync.domain.services.ts_guard import (
    GuardDecision,
    OrgSyncTsGuard,
)
from bisheng.sso_sync.domain.schemas.payloads import (
    BatchResult,
    DepartmentsSyncRequest,
    DepartmentUpsertItem,
)
from bisheng.sso_sync.domain.services.dept_upsert_service import (
    DeptUpsertService,
)
from bisheng.tenant.domain.constants import DeletionSource
from bisheng.tenant.domain.services.department_deletion_handler import (
    DepartmentDeletionHandler,
)


class DepartmentsSyncService:

    SOURCE = 'sso'

    @classmethod
    async def execute(
        cls, payload: DepartmentsSyncRequest, request_ip: str = '',
    ) -> BatchResult:
        result = BatchResult()

        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                # --- upsert round ---
                for item in payload.upsert:
                    await cls._apply_upsert(item, payload.source_ts, result)

                # --- remove round ---
                for ext_id in payload.remove:
                    await cls._apply_remove(
                        ext_id, payload.source_ts, result, request_ip,
                    )
            finally:
                current_tenant_id.reset(token)

        return result

    # -----------------------------------------------------------------------
    # Per-item handlers (each in its own try/except — per AC-11).
    # -----------------------------------------------------------------------

    @classmethod
    async def _apply_upsert(
        cls,
        item: DepartmentUpsertItem,
        source_ts: Optional[int],
        result: BatchResult,
    ) -> None:
        try:
            existing = await DepartmentDao.aget_by_source_external_id(
                cls.SOURCE, item.external_id,
            )
            incoming_ts = int(item.ts or source_ts or 0)
            decision = await OrgSyncTsGuard.check_and_update(
                existing, incoming_ts, 'upsert',
            )
            if decision == GuardDecision.SKIP_TS:
                result.skipped_ts_conflict += 1
                logger.info(
                    'F014 upsert skipped by ts guard: external_id=%s '
                    'incoming_ts=%s last=%s',
                    item.external_id, incoming_ts,
                    getattr(existing, 'last_sync_ts', 0),
                )
                return
            await DeptUpsertService.upsert_from_sync_payload(
                existing=existing,
                item=item,
                source=cls.SOURCE,
                last_sync_ts=incoming_ts,
            )
            result.applied_upsert += 1
        except Exception as exc:  # noqa: BLE001 — per-item isolation
            logger.warning(
                'F014 upsert error for %s: %s', item.external_id, exc,
            )
            result.errors.append({
                'type': 'upsert_error',
                'external_id': item.external_id,
                'error': str(exc),
            })

    @classmethod
    async def _apply_remove(
        cls,
        external_id: str,
        source_ts: Optional[int],
        result: BatchResult,
        request_ip: str,
    ) -> None:
        try:
            dept = await DepartmentDao.aget_by_source_external_id(
                cls.SOURCE, external_id,
            )
            if dept is None:
                # Nothing to do; not an error. Happens on double-delete.
                logger.info(
                    'F014 remove skipped: external_id=%s not present',
                    external_id,
                )
                return

            incoming_ts = int(source_ts or 0)
            decision = await OrgSyncTsGuard.check_and_update(
                dept, incoming_ts, 'remove',
            )
            if decision == GuardDecision.SKIP_TS:
                result.skipped_ts_conflict += 1
                logger.info(
                    'F014 remove skipped by ts guard: external_id=%s '
                    'incoming_ts=%s last=%s',
                    external_id, incoming_ts, dept.last_sync_ts,
                )
                return

            mounted_before = dept.mounted_tenant_id
            await DepartmentDao.aarchive_by_external_id(
                source=cls.SOURCE,
                external_id=external_id,
                last_sync_ts=incoming_ts,
            )
            # F011 orphan handler owns the tenant.orphaned audit + notify
            # pipeline; we only trigger it with the right deletion_source.
            await DepartmentDeletionHandler.on_deleted(
                dept_id=dept.id,
                deletion_source=DeletionSource.SSO_REALTIME,
            )
            if mounted_before:
                result.orphan_triggered.append(mounted_before)
            result.applied_remove += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'F014 remove error for %s: %s', external_id, exc,
            )
            result.errors.append({
                'type': 'remove_error',
                'external_id': external_id,
                'error': str(exc),
            })
