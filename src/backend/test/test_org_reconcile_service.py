"""Integration tests for F015 :class:`OrgReconcileService`.

These tests exercise the 11-step orchestration with every I/O boundary
mocked. We are not verifying F011/F012/F014 primitives here — those have
their own tests. What matters for F015 is:

- The right primitives are called with the right arguments.
- AC-02/03/04/09/10/11 branches fire under the documented preconditions.
- The Redis SETNX lock serialises reconciles per config (AC-13 precursor).

The shared ``reconcile_mocks`` fixture monkeypatches every external
function the service imports by name, so each test body reads like a
straight scenario script.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO


MODULE = 'bisheng.org_sync.domain.services.reconcile_service'


# ---------------------------------------------------------------------------
# Local stand-ins
# ---------------------------------------------------------------------------


def _make_config(
    *, id=1, tenant_id=1, provider='feishu', status='active',
    auth_config='', sync_scope=None,
):
    return SimpleNamespace(
        id=id, tenant_id=tenant_id, provider=provider, status=status,
        auth_config=auth_config, sync_scope=sync_scope,
    )


def _make_dept(
    *, id, external_id, name='Dept', last_sync_ts=0, is_deleted=0,
    is_tenant_root=0, mounted_tenant_id=None, parent_id=None,
):
    return SimpleNamespace(
        id=id, external_id=external_id, name=name,
        last_sync_ts=last_sync_ts, is_deleted=is_deleted,
        is_tenant_root=is_tenant_root, mounted_tenant_id=mounted_tenant_id,
        parent_id=parent_id, source='feishu',
    )


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal async-compatible stand-in for redis client used by the lock.

    ``set(nx=True)`` returns True on first call, False when the key already
    exists — mirrors production Redis SETNX semantics closely enough for
    the lock tests.
    """

    def __init__(self):
        self._store: dict[str, bytes] = {}
        self.async_connection = self

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self._store:
            return False
        self._store[key] = value
        self.last_ex = ex
        return True

    async def delete(self, key):
        self._store.pop(key, None)


@pytest.fixture()
def reconcile_mocks(monkeypatch):
    """Patch every external dependency of OrgReconcileService by name.

    Returns a ``SimpleNamespace`` of handles so individual tests can
    assert call counts / arguments without re-patching.
    """
    # Settings handle (only reconcile.redis_lock_ttl_seconds is read)
    fake_settings = SimpleNamespace(
        reconcile=SimpleNamespace(redis_lock_ttl_seconds=1800),
    )
    monkeypatch.setattr(f'{MODULE}.settings', fake_settings)

    # Redis client
    fake_redis = _FakeRedis()
    async def _get_redis():
        return fake_redis
    monkeypatch.setattr(f'{MODULE}.get_redis_client', _get_redis)

    # OrgSyncConfigDao.aget_by_id
    aget_by_id = AsyncMock()
    monkeypatch.setattr(f'{MODULE}.OrgSyncConfigDao.aget_by_id', aget_by_id)

    # Provider
    fake_provider = MagicMock()
    fake_provider.authenticate = AsyncMock(return_value=True)
    fake_provider.fetch_departments = AsyncMock(return_value=[])
    get_provider = MagicMock(return_value=fake_provider)
    monkeypatch.setattr(f'{MODULE}.get_provider', get_provider)
    monkeypatch.setattr(
        f'{MODULE}.decrypt_auth_config', MagicMock(return_value={}))

    # DepartmentDao
    aget_active_by_tenant = AsyncMock(return_value=[])
    aget_by_source_ext = AsyncMock(return_value=None)
    aupsert = AsyncMock()
    aarchive = AsyncMock()
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aget_active_by_tenant', aget_active_by_tenant)
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aget_by_source_external_id', aget_by_source_ext)
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aarchive_by_external_id', aarchive)

    # DeptUpsertService
    upsert_from_payload = AsyncMock()
    monkeypatch.setattr(
        f'{MODULE}.DeptUpsertService.upsert_from_sync_payload',
        upsert_from_payload)

    # DepartmentDeletionHandler + UserTenantSyncService
    on_deleted = AsyncMock()
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDeletionHandler.on_deleted', on_deleted)
    sync_user = AsyncMock(return_value=MagicMock(id=1))
    monkeypatch.setattr(
        f'{MODULE}.UserTenantSyncService.sync_user', sync_user)

    # UserDepartmentDao
    aget_user_ids = AsyncMock(return_value=[])
    monkeypatch.setattr(
        f'{MODULE}.UserDepartmentDao.aget_user_ids_by_department',
        aget_user_ids)

    # AuditLogDao.ainsert_v2
    ainsert_v2 = AsyncMock()
    monkeypatch.setattr(f'{MODULE}.AuditLogDao.ainsert_v2', ainsert_v2)

    # OrgSyncLogDao.acreate_event + flush_log
    acreate_event = AsyncMock()
    monkeypatch.setattr(
        f'{MODULE}.OrgSyncLogDao.acreate_event', acreate_event)
    flush_log = AsyncMock()
    monkeypatch.setattr(f'{MODULE}.flush_log', flush_log)

    # TsGuard stays REAL — it is a pure function and we want its
    # INV-T12 decision matrix to feed real APPLY / SKIP_TS verdicts.

    return SimpleNamespace(
        settings=fake_settings,
        redis=fake_redis,
        aget_by_id=aget_by_id,
        provider=fake_provider,
        get_provider=get_provider,
        aget_active_by_tenant=aget_active_by_tenant,
        aget_by_source_ext=aget_by_source_ext,
        upsert_from_payload=upsert_from_payload,
        aarchive=aarchive,
        on_deleted=on_deleted,
        sync_user=sync_user,
        aget_user_ids=aget_user_ids,
        ainsert_v2=ainsert_v2,
        acreate_event=acreate_event,
        flush_log=flush_log,
    )


# ---------------------------------------------------------------------------
# AC-02 / AC-03 / AC-04 — orchestration branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReconcileHappyBranches:

    async def test_reconcile_new_dept_upserts_preserves_mount(self, reconcile_mocks):
        """AC-02: a remote-only dept triggers upsert without touching mount flags."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=7)
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='NEW1', name='New'),
        ]
        reconcile_mocks.aget_active_by_tenant.return_value = []

        result = await OrgReconcileService.reconcile_config(7)

        assert result.skipped is False
        assert result.applied_upsert == 1
        assert result.applied_archive == 0
        reconcile_mocks.upsert_from_payload.assert_awaited_once()
        kwargs = reconcile_mocks.upsert_from_payload.await_args.kwargs
        assert kwargs['existing'] is None  # new row
        assert kwargs['source'] == 'feishu'
        assert kwargs['last_sync_ts'] > 0
        assert kwargs['item'].external_id == 'NEW1'
        # Mount fields are never passed to upsert_from_payload (AC-02).
        assert not hasattr(kwargs['item'], 'is_tenant_root')

    async def test_reconcile_removed_dept_triggers_department_deletion_handler(
        self, reconcile_mocks,
    ):
        """AC-03: remote drops a dept → archive + DepartmentDeletionHandler fires
        with ``DeletionSource.CELERY_RECONCILE``."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        from bisheng.tenant.domain.constants import DeletionSource

        reconcile_mocks.aget_by_id.return_value = _make_config(id=8)
        # Remote empty; local has E1.
        local = _make_dept(
            id=42, external_id='E1', last_sync_ts=100, mounted_tenant_id=9,
        )
        reconcile_mocks.aget_active_by_tenant.return_value = [local]
        reconcile_mocks.aget_by_source_ext.return_value = local
        reconcile_mocks.provider.fetch_departments.return_value = []

        result = await OrgReconcileService.reconcile_config(8)

        assert result.applied_archive == 1
        reconcile_mocks.aarchive.assert_awaited_once()
        reconcile_mocks.on_deleted.assert_awaited_once()
        args, kwargs = reconcile_mocks.on_deleted.await_args
        # The handler is called positionally with (dept_id, source)
        assert args[0] == 42
        assert args[1] == DeletionSource.CELERY_RECONCILE

    async def test_reconcile_primary_dept_change_triggers_user_tenant_sync(
        self, reconcile_mocks,
    ):
        """AC-04: a cross-tenant move fires UserTenantSyncService per primary
        member with ``CELERY_RECONCILE`` trigger (so token_version +1 + JWT
        invalidation happens)."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger

        reconcile_mocks.aget_by_id.return_value = _make_config(id=9)
        mount_a = _make_dept(
            id=1, external_id='MA', is_tenant_root=1, mounted_tenant_id=10,
        )
        mount_b = _make_dept(
            id=2, external_id='MB', is_tenant_root=1, mounted_tenant_id=20,
        )
        leaf = _make_dept(id=3, external_id='E1', parent_id=1)
        reconcile_mocks.aget_active_by_tenant.return_value = [
            mount_a, mount_b, leaf,
        ]
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='MA', name='MountA'),
            RemoteDepartmentDTO(external_id='MB', name='MountB'),
            RemoteDepartmentDTO(
                external_id='E1', name='Dept', parent_external_id='MB'),
        ]
        reconcile_mocks.aget_user_ids.return_value = [101, 102]

        result = await OrgReconcileService.reconcile_config(9)

        assert result.cross_tenant_moves == 1
        assert result.user_syncs_triggered == 2
        # Each primary member gets sync_user(..., trigger=CELERY_RECONCILE)
        assert reconcile_mocks.sync_user.await_count == 2
        for call in reconcile_mocks.sync_user.await_args_list:
            assert call.kwargs['trigger'] == UserTenantSyncTrigger.CELERY_RECONCILE


# ---------------------------------------------------------------------------
# AC-09 / AC-10 — ts guard applied via event rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTsGuardBranches:

    async def test_reconcile_stale_ts_skipped_writes_warn_event(
        self, reconcile_mocks, monkeypatch,
    ):
        """AC-09: incoming ts older than last_sync_ts → SKIP_TS + stale_ts warn row."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=11)
        # Freeze the service's "now" to 500 so the guard compares against
        # last_sync_ts=10_000 → stale.
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 500)
        existing = _make_dept(id=1, external_id='E1', last_sync_ts=10_000)
        reconcile_mocks.aget_active_by_tenant.return_value = [existing]
        reconcile_mocks.aget_by_source_ext.return_value = existing
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='E1', name='ChangedName'),
        ]

        result = await OrgReconcileService.reconcile_config(11)

        assert result.applied_upsert == 0
        assert result.skipped_ts == 1
        reconcile_mocks.upsert_from_payload.assert_not_awaited()
        reconcile_mocks.acreate_event.assert_awaited()
        kwargs = reconcile_mocks.acreate_event.await_args.kwargs
        assert kwargs['event_type'] == 'stale_ts'
        assert kwargs['level'] == 'warn'
        assert kwargs['external_id'] == 'E1'

    async def test_reconcile_newer_ts_applies_and_updates_last_sync_ts(
        self, reconcile_mocks, monkeypatch,
    ):
        """AC-10: incoming ts newer than last_sync_ts → APPLY upsert path
        and ``last_sync_ts`` propagated via ``DeptUpsertService``."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=12)
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 50_000)
        existing = _make_dept(id=1, external_id='E1', last_sync_ts=10_000)
        reconcile_mocks.aget_active_by_tenant.return_value = [existing]
        reconcile_mocks.aget_by_source_ext.return_value = existing
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='E1', name='ChangedName'),
        ]

        result = await OrgReconcileService.reconcile_config(12)

        assert result.applied_upsert == 1
        reconcile_mocks.upsert_from_payload.assert_awaited_once()
        kwargs = reconcile_mocks.upsert_from_payload.await_args.kwargs
        assert kwargs['last_sync_ts'] == 50_000
        assert kwargs['item'].ts == 50_000


# ---------------------------------------------------------------------------
# AC-11 — same-ts upsert vs remove → remove wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSameTsRemoveWins:

    async def test_reconcile_same_ts_upsert_then_remove_prefers_remove(
        self, reconcile_mocks, monkeypatch,
    ):
        """AC-11: Gateway already upserted E1 at T; Celery's same-T archive
        MUST apply + write ``ts_conflict`` event row + audit_log."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=13)
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 7_000)
        # Gateway already wrote E1 with last_sync_ts=7_000, is_deleted=0.
        existing = _make_dept(
            id=42, external_id='E1', last_sync_ts=7_000, is_deleted=0,
            mounted_tenant_id=3,
        )
        reconcile_mocks.aget_active_by_tenant.return_value = [existing]
        reconcile_mocks.aget_by_source_ext.return_value = existing
        # Remote tree no longer lists E1 → diff emits an ArchiveOp.
        reconcile_mocks.provider.fetch_departments.return_value = []

        result = await OrgReconcileService.reconcile_config(13)

        assert result.applied_archive == 1
        assert result.conflicts == 1
        # Archive must still execute — remove wins.
        reconcile_mocks.aarchive.assert_awaited_once()
        reconcile_mocks.on_deleted.assert_awaited_once()
        # ts_conflict event row written.
        event_calls = [
            c for c in reconcile_mocks.acreate_event.await_args_list
            if c.kwargs.get('event_type') == 'ts_conflict'
        ]
        assert len(event_calls) == 1
        assert event_calls[0].kwargs['external_id'] == 'E1'
        assert event_calls[0].kwargs['level'] == 'warn'
        # audit_log.action='dept.sync_conflict'
        reconcile_mocks.ainsert_v2.assert_awaited()
        audit_kwargs = reconcile_mocks.ainsert_v2.await_args.kwargs
        assert audit_kwargs['action'] == 'dept.sync_conflict'
        assert audit_kwargs['metadata']['resolution'] == 'remove_wins'
        assert audit_kwargs['metadata']['via'] == 'celery_reconcile'


# ---------------------------------------------------------------------------
# AC-13 precursor + SSO seed skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLockingAndSkip:

    async def test_reconcile_redis_lock_busy_raises_19314(
        self, reconcile_mocks,
    ):
        """AC-13 building block: second invocation on the same config_id
        while the lock is held raises 19314."""
        from bisheng.common.errcode.sso_sync import SsoReconcileLockBusyError
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=14)

        # Pre-acquire the lock manually to simulate a concurrent worker.
        await reconcile_mocks.redis.set(
            'org_reconcile:14', b'1', nx=True, ex=1800)

        with pytest.raises(Exception) as excinfo:
            await OrgReconcileService.reconcile_config(14)
        # SsoReconcileLockBusyError.http_exception() wraps the code
        # in an HTTPException-compatible error; the response payload
        # (or the raised exception type) must still map to 19314.
        expected_code = SsoReconcileLockBusyError.Code
        msg = str(excinfo.value)
        assert str(expected_code) in msg or expected_code in getattr(
            excinfo.value, 'args', ())

    async def test_reconcile_skips_sso_realtime_seed_config(
        self, reconcile_mocks,
    ):
        """F014 seed (id=9999, provider='sso_realtime') must never talk to
        a provider — it exists only to anchor HMAC log rows."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(
            id=9999, provider='sso_realtime',
        )

        result = await OrgReconcileService.reconcile_config(9999)

        assert result.skipped is True
        assert result.skip_reason == 'sso_realtime_seed'
        reconcile_mocks.get_provider.assert_not_called()
        reconcile_mocks.provider.fetch_departments.assert_not_called()
        reconcile_mocks.aarchive.assert_not_called()


# ---------------------------------------------------------------------------
# T11: event row persistence specifics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEventRowPersistence:
    """T11 — zoom in on acreate_event call kwargs so regressions on the
    event-row schema surface immediately."""

    async def test_stale_ts_event_written_with_level_warn_and_event_type_stale_ts(
        self, reconcile_mocks, monkeypatch,
    ):
        """AC-09 persistence dimension: stale ts → event row has the
        expected level/event_type/external_id/source_ts."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=61)
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 500)
        existing = _make_dept(id=1, external_id='E-STALE', last_sync_ts=10_000)
        reconcile_mocks.aget_active_by_tenant.return_value = [existing]
        reconcile_mocks.aget_by_source_ext.return_value = existing
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='E-STALE', name='Stale'),
        ]

        await OrgReconcileService.reconcile_config(61)

        reconcile_mocks.acreate_event.assert_awaited_once()
        kwargs = reconcile_mocks.acreate_event.await_args.kwargs
        assert kwargs['event_type'] == 'stale_ts'
        assert kwargs['level'] == 'warn'
        assert kwargs['external_id'] == 'E-STALE'
        assert kwargs['source_ts'] == 500
        assert kwargs['config_id'] == 61
        assert kwargs['tenant_id'] == 1

    async def test_same_ts_conflict_event_written_with_external_id_and_source_ts(
        self, reconcile_mocks, monkeypatch,
    ):
        """AC-11 persistence: ts_conflict row has both external_id and
        source_ts populated so the weekly aggregator can find it."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=62)
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 9_000)
        existing = _make_dept(
            id=1, external_id='E-CONFLICT', last_sync_ts=9_000, is_deleted=0,
        )
        reconcile_mocks.aget_active_by_tenant.return_value = [existing]
        reconcile_mocks.aget_by_source_ext.return_value = existing
        reconcile_mocks.provider.fetch_departments.return_value = []

        await OrgReconcileService.reconcile_config(62)

        ts_conflicts = [
            c for c in reconcile_mocks.acreate_event.await_args_list
            if c.kwargs.get('event_type') == 'ts_conflict'
        ]
        assert len(ts_conflicts) == 1
        kwargs = ts_conflicts[0].kwargs
        assert kwargs['level'] == 'warn'
        assert kwargs['external_id'] == 'E-CONFLICT'
        assert kwargs['source_ts'] == 9_000
        assert 'resolution' in (kwargs.get('error_details') or {})

    async def test_conflict_event_distinct_from_batch_summary_row(
        self, reconcile_mocks, monkeypatch,
    ):
        """One reconcile run produces (a) a batch summary row (via
        flush_log) AND (b) event rows (via acreate_event). The two
        are never conflated."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=63)
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 500)
        # One stale op forces one event row.
        existing = _make_dept(id=1, external_id='E', last_sync_ts=10_000)
        reconcile_mocks.aget_active_by_tenant.return_value = [existing]
        reconcile_mocks.aget_by_source_ext.return_value = existing
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='E', name='E'),
        ]

        await OrgReconcileService.reconcile_config(63)

        # Batch summary went through flush_log exactly once.
        reconcile_mocks.flush_log.assert_awaited_once()
        # Event row went through acreate_event exactly once.
        assert reconcile_mocks.acreate_event.await_count == 1
        # flush_log was called with trigger_type='reconcile' (not an event).
        flush_kwargs = reconcile_mocks.flush_log.await_args.kwargs
        assert flush_kwargs['trigger_type'] == 'reconcile'
        # acreate_event carries event_type != ''.
        event_kwargs = reconcile_mocks.acreate_event.await_args.kwargs
        assert event_kwargs['event_type'] != ''

    async def test_event_rows_written_even_when_one_persist_fails(
        self, reconcile_mocks, monkeypatch,
    ):
        """If the first acreate_event raises, subsequent rows still get
        written — the reconcile loop swallows per-row failures."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=64)
        monkeypatch.setattr(f'{MODULE}.time.time', lambda: 500)
        # Two stale ops → two event rows expected.
        a = _make_dept(id=1, external_id='A', last_sync_ts=10_000)
        b = _make_dept(id=2, external_id='B', last_sync_ts=10_000)
        reconcile_mocks.aget_active_by_tenant.return_value = [a, b]
        # aget_by_source_ext returns whichever dept was requested
        async def _side(source, external_id):
            return {'A': a, 'B': b}.get(external_id)
        reconcile_mocks.aget_by_source_ext.side_effect = _side
        reconcile_mocks.provider.fetch_departments.return_value = [
            RemoteDepartmentDTO(external_id='A', name='A'),
            RemoteDepartmentDTO(external_id='B', name='B'),
        ]
        # First acreate_event raises; second succeeds.
        side_effects = [RuntimeError('boom'), None]
        reconcile_mocks.acreate_event.side_effect = side_effects

        result = await OrgReconcileService.reconcile_config(64)

        assert reconcile_mocks.acreate_event.await_count == 2
        # The run recorded the failed row in errors.
        assert any('event_row' in e for e in result.errors)


# ---------------------------------------------------------------------------
# T14: Redis SETNX concurrency + lock lifecycle (AC-13, INV-T12 atomicity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLockSemantics:

    async def test_concurrent_same_ts_same_config_deduped_by_setnx(
        self, reconcile_mocks,
    ):
        """AC-13: overlapping runs on the same config_id — only one holds
        the lock; the other gets 19314."""
        import asyncio
        from bisheng.common.errcode.sso_sync import SsoReconcileLockBusyError
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=71)

        # Force the critical section to actually be concurrent by
        # inserting an await point — the provider fetch suspends until
        # released. The second caller must try to acquire the lock
        # while the first still holds it.
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_fetch(*_a, **_kw):
            started.set()
            await release.wait()
            return []

        reconcile_mocks.provider.fetch_departments.side_effect = slow_fetch

        first = asyncio.create_task(
            OrgReconcileService.reconcile_config(71))
        await started.wait()
        # Second call races in while the first is still inside _run.
        try:
            with pytest.raises(Exception) as excinfo:
                await OrgReconcileService.reconcile_config(71)
            expected_code = SsoReconcileLockBusyError.Code
            assert str(expected_code) in str(excinfo.value) or (
                expected_code in getattr(excinfo.value, 'args', ())
            )
        finally:
            release.set()
            await first

    async def test_different_config_ids_lock_independently(
        self, reconcile_mocks,
    ):
        """Lock is scoped per config_id — two different configs can run
        concurrently."""
        import asyncio
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        # aget_by_id returns a different config depending on call id.
        def _side(cid):
            return _make_config(id=cid)
        reconcile_mocks.aget_by_id.side_effect = _side

        started1 = asyncio.Event()
        release1 = asyncio.Event()

        async def slow_fetch(*_a, **_kw):
            started1.set()
            await release1.wait()
            return []

        reconcile_mocks.provider.fetch_departments.side_effect = slow_fetch

        task1 = asyncio.create_task(
            OrgReconcileService.reconcile_config(81))
        await started1.wait()
        # config 82 should acquire its own lock cleanly (no wait).
        # Replace the slow side_effect for the second call so it can
        # return immediately.
        reconcile_mocks.provider.fetch_departments.side_effect = None
        reconcile_mocks.provider.fetch_departments.return_value = []
        result2 = await asyncio.wait_for(
            OrgReconcileService.reconcile_config(82), timeout=1.0,
        )
        assert result2.skipped is False
        # Now release task1.
        release1.set()
        result1 = await task1
        assert result1.skipped is False

    async def test_lock_released_even_on_exception(self, reconcile_mocks):
        """The contextmanager deletes the Redis key in `finally:` even
        when the service body raises — a subsequent reconcile on the
        same config_id must succeed."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=91)
        reconcile_mocks.provider.authenticate.side_effect = RuntimeError(
            'simulated auth failure')

        # First run: auth raises -> captured as result.errors, lock released.
        result1 = await OrgReconcileService.reconcile_config(91)
        assert any('authenticate' in e for e in result1.errors)

        # Second run: no raise anymore → must proceed cleanly.
        reconcile_mocks.provider.authenticate.side_effect = None
        reconcile_mocks.provider.authenticate.return_value = True
        result2 = await OrgReconcileService.reconcile_config(91)
        assert result2.errors == []

    async def test_lock_ttl_30min_prevents_stuck_lock(self, reconcile_mocks):
        """The SETNX call must request an explicit ex= (30min by default)
        so a crashed worker cannot hold the lock forever."""
        from bisheng.org_sync.domain.services.reconcile_service import (
            OrgReconcileService,
        )
        reconcile_mocks.aget_by_id.return_value = _make_config(id=92)
        await OrgReconcileService.reconcile_config(92)
        # _FakeRedis stored the last ex value in .last_ex.
        assert reconcile_mocks.redis.last_ex == 1800
