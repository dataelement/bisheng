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

from typing import Dict, Optional

from loguru import logger

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.org_sync.domain.services.ts_guard import (
    GuardDecision,
    OrgSyncTsGuard,
)
from bisheng.sso_sync.domain.constants import SSO_SOURCE
from bisheng.sso_sync.domain.schemas.payloads import (
    BatchResult,
    DepartmentsSyncRequest,
    DepartmentUpsertItem,
)
from bisheng.department.domain.services.department_archive_cleanup_service import (
    DepartmentArchiveCleanupService,
)
from bisheng.sso_sync.domain.services.dept_upsert_service import (
    DeptUpsertService,
)
from bisheng.tenant.domain.constants import DeletionSource
from bisheng.tenant.domain.services.department_deletion_handler import (
    DepartmentDeletionHandler,
)


class DepartmentsSyncService:

    SOURCE = SSO_SOURCE

    @classmethod
    async def execute(
        cls,
        payload: DepartmentsSyncRequest,
        request_ip: str = '',
        row_source: str = SSO_SOURCE,
    ) -> BatchResult:
        result = BatchResult()

        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                # Preload parent rows once per batch. For a push of N items
                # sharing M distinct parents, this replaces O(N) parent
                # lookups inside ``upsert_from_sync_payload`` with M
                # lookups up front; items inserting a brand-new parent in
                # the same batch still hit the DAO fallback inside the
                # upsert service (cache miss → single query).
                parent_cache = await cls._preload_parent_cache(
                    payload.upsert, row_source,
                )

                # --- upsert round ---
                for item in payload.upsert:
                    await cls._apply_upsert(
                        item,
                        payload.source_ts,
                        result,
                        parent_cache,
                        row_source,
                    )
                    # Freshly upserted rows can become parents for later
                    # items in the same batch — keep the cache in sync so
                    # subsequent children don't re-query the DAO.
                    if item.external_id not in parent_cache:
                        fresh = await DepartmentDao.aget_by_source_external_id(
                            row_source, item.external_id,
                        )
                        if fresh is not None:
                            parent_cache[item.external_id] = fresh

                # --- remove round ---
                for ext_id in payload.remove:
                    await cls._apply_remove(
                        ext_id,
                        payload.source_ts,
                        result,
                        request_ip,
                        row_source,
                    )
            finally:
                current_tenant_id.reset(token)

        return result

    @classmethod
    async def _preload_parent_cache(
        cls, upsert_items, row_source: str,
    ) -> Dict[str, Department]:
        """Gather every parent_external_id referenced by the upsert batch
        and load them with a single DAO lookup per distinct parent.
        Items whose parent is itself part of the same batch are
        skipped — they'll be cached after their own upsert lands.
        """
        item_ext_ids = {it.external_id for it in upsert_items}
        parent_ext_ids = {
            it.parent_external_id
            for it in upsert_items
            if it.parent_external_id
            and it.parent_external_id not in item_ext_ids
        }
        cache: Dict[str, Department] = {}
        for ext in parent_ext_ids:
            row = await DepartmentDao.aget_by_source_external_id(row_source, ext)
            if row is not None:
                cache[ext] = row
        return cache

    # -----------------------------------------------------------------------
    # Per-item handlers (each in its own try/except — per AC-11).
    # -----------------------------------------------------------------------

    @classmethod
    async def _apply_upsert(
        cls,
        item: DepartmentUpsertItem,
        source_ts: Optional[int],
        result: BatchResult,
        parent_cache: Optional[Dict[str, Department]] = None,
        row_source: str = SSO_SOURCE,
    ) -> None:
        try:
            existing = await DepartmentDao.aget_by_source_external_id(
                row_source, item.external_id,
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
                source=row_source,
                last_sync_ts=incoming_ts,
                parent_cache=parent_cache,
            )
            result.applied_upsert += 1
        except Exception as exc:  # noqa: BLE001 — per-item isolation
            # AC-11: one malformed external_id, DB constraint violation or
            # transient failure must not abort the whole batch; record and
            # move on.
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
        row_source: str = SSO_SOURCE,
    ) -> None:
        try:
            dept = await DepartmentDao.aget_by_source_external_id(
                row_source, external_id,
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
                source=row_source,
                external_id=external_id,
                last_sync_ts=incoming_ts,
            )
            await DepartmentArchiveCleanupService.arun_for_archived_department(
                int(dept.id), reason='f014_department_remove',
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
