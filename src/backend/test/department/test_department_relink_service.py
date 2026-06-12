"""Unit tests for F015 :class:`DepartmentRelinkService`.

Mocks every DAO + the conflict store; the tests script scenarios and
assert the right DAO calls, audit entries, and response DTOs. AC
coverage:

- AC-05: ``external_id_map`` strategy.
- AC-06: ``path_plus_name`` single auto-apply + multi-candidate conflict
  persistence.
- AC-07: ``dry_run`` returns ``would_apply`` without DB writes.
- Error surfaces: 19315 unknown strategy, 19316 resolve-conflict with
  invalid chosen candidate.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import (
    SsoRelinkConflictUnresolvedError,
    SsoRelinkStrategyUnsupportedError,
)
from bisheng.org_sync.domain.schemas.relink import RelinkRequest


MODULE = 'bisheng.org_sync.domain.services.relink_service'


def _dept(*, id, external_id='OLD', path='/Root/A', name='A', tenant_id=1):
    return SimpleNamespace(
        id=id, external_id=external_id, path=path, name=name,
        tenant_id=tenant_id,
    )


@pytest.fixture()
def relink_mocks(monkeypatch):
    aget_by_source_ext = AsyncMock()
    aget_by_id = AsyncMock()
    aget_candidates = AsyncMock(return_value=[])
    aupdate_external_id = AsyncMock(return_value=True)
    ainsert_v2 = AsyncMock()

    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aget_by_source_external_id',
        aget_by_source_ext)
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aget_by_id', aget_by_id)
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aget_active_by_source_path_name',
        aget_candidates)
    monkeypatch.setattr(
        f'{MODULE}.DepartmentDao.aupdate_external_id', aupdate_external_id)
    monkeypatch.setattr(
        f'{MODULE}.AuditLogDao.ainsert_v2', ainsert_v2)

    # Swap ``DepartmentRelinkService.store`` with a fresh mock per test so
    # tests that do NOT touch path_plus_name are not polluted by leftover
    # store state from previous cases.
    fake_store = SimpleNamespace(
        save=AsyncMock(),
        get=AsyncMock(return_value=[]),
        delete=AsyncMock(),
    )
    from bisheng.org_sync.domain.services.relink_service import (
        DepartmentRelinkService,
    )
    monkeypatch.setattr(DepartmentRelinkService, 'store', fake_store)

    return SimpleNamespace(
        aget_by_source_ext=aget_by_source_ext,
        aget_by_id=aget_by_id,
        aget_candidates=aget_candidates,
        aupdate_external_id=aupdate_external_id,
        ainsert_v2=ainsert_v2,
        store=fake_store,
    )


# ---------------------------------------------------------------------------
# Strategy: external_id_map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExternalIdMapStrategy:

    async def test_external_id_map_strategy_applies(self, relink_mocks):
        """AC-05"""
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.aget_by_source_ext.return_value = _dept(
            id=42, external_id='OLD-A')
        req = RelinkRequest(
            old_external_ids=['OLD-A'],
            matching_strategy='external_id_map',
            external_id_map={'OLD-A': 'NEW-A'},
            source='sso',
        )
        resp = await DepartmentRelinkService.relink(req)

        assert len(resp.applied) == 1
        assert resp.applied[0].dept_id == 42
        assert resp.applied[0].new_external_id == 'NEW-A'
        relink_mocks.aupdate_external_id.assert_awaited_once_with(
            42, 'NEW-A')
        relink_mocks.ainsert_v2.assert_awaited_once()
        audit_kwargs = relink_mocks.ainsert_v2.await_args.kwargs
        assert audit_kwargs['action'] == 'dept.relink_applied'
        assert audit_kwargs['metadata']['strategy'] == 'external_id_map'

    async def test_external_id_map_skips_missing_dept(self, relink_mocks):
        """Non-existent old_ext must not crash — simply skip."""
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.aget_by_source_ext.return_value = None
        req = RelinkRequest(
            old_external_ids=['GHOST'],
            matching_strategy='external_id_map',
            external_id_map={'GHOST': 'NEW'},
        )
        resp = await DepartmentRelinkService.relink(req)

        assert resp.applied == []
        relink_mocks.aupdate_external_id.assert_not_awaited()


# ---------------------------------------------------------------------------
# Strategy: path_plus_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPathPlusNameStrategy:

    async def test_path_plus_name_single_candidate_auto_apply(
        self, relink_mocks,
    ):
        """AC-06 single-candidate"""
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.aget_by_source_ext.return_value = _dept(
            id=5, external_id='OLD', path='/Root/A', name='A')
        relink_mocks.aget_candidates.return_value = [
            _dept(id=99, external_id='NEW-A', path='/Root/A', name='A'),
        ]
        req = RelinkRequest(
            old_external_ids=['OLD'],
            matching_strategy='path_plus_name',
        )
        resp = await DepartmentRelinkService.relink(req)

        assert len(resp.applied) == 1
        assert resp.applied[0].new_external_id == 'NEW-A'
        assert resp.conflicts == []
        relink_mocks.aupdate_external_id.assert_awaited_once_with(
            5, 'NEW-A')
        relink_mocks.store.save.assert_not_awaited()

    async def test_path_plus_name_multi_candidate_returns_conflicts(
        self, relink_mocks,
    ):
        """AC-06 multi-candidate — no auto-apply, conflicts persisted."""
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.aget_by_source_ext.return_value = _dept(
            id=5, external_id='OLD', path='/Root/A', name='A')
        relink_mocks.aget_candidates.return_value = [
            _dept(id=97, external_id='NEW-A1', path='/Root/A', name='A'),
            _dept(id=98, external_id='NEW-A2', path='/Root/A', name='A'),
        ]
        req = RelinkRequest(
            old_external_ids=['OLD'],
            matching_strategy='path_plus_name',
        )
        resp = await DepartmentRelinkService.relink(req)

        assert resp.applied == []
        assert len(resp.conflicts) == 1
        assert resp.conflicts[0].dept_id == 5
        assert len(resp.conflicts[0].candidates) == 2
        relink_mocks.aupdate_external_id.assert_not_awaited()
        relink_mocks.store.save.assert_awaited_once()
        # Store was handed the candidate dicts untouched.
        store_args = relink_mocks.store.save.await_args.args
        assert store_args[0] == 5
        assert {c['new_external_id'] for c in store_args[1]} == {
            'NEW-A1', 'NEW-A2'}


# ---------------------------------------------------------------------------
# dry_run (AC-07)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDryRun:

    async def test_dry_run_returns_would_apply_no_db_write(self, relink_mocks):
        """AC-07"""
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.aget_by_source_ext.return_value = _dept(
            id=42, external_id='OLD-A')
        req = RelinkRequest(
            old_external_ids=['OLD-A'],
            matching_strategy='external_id_map',
            external_id_map={'OLD-A': 'NEW-A'},
            dry_run=True,
        )
        resp = await DepartmentRelinkService.relink(req)

        assert resp.applied == []
        assert len(resp.would_apply) == 1
        assert resp.would_apply[0].new_external_id == 'NEW-A'
        relink_mocks.aupdate_external_id.assert_not_awaited()
        relink_mocks.ainsert_v2.assert_not_awaited()


# ---------------------------------------------------------------------------
# Unknown strategy (19315)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUnknownStrategy:

    async def test_relink_unknown_strategy_raises_19315(self, relink_mocks):
        """Pydantic Literal rejects invalid strategies at construction
        time, so the service branch only fires if the caller constructs
        a RelinkRequest via model_construct (bypassing validation) — we
        replicate that here to verify the explicit raise path."""
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        req = RelinkRequest.model_construct(
            old_external_ids=['x'],
            matching_strategy='invalid_strategy',
        )
        with pytest.raises(Exception) as excinfo:
            await DepartmentRelinkService.relink(req)
        assert str(SsoRelinkStrategyUnsupportedError.Code) in str(
            excinfo.value) or SsoRelinkStrategyUnsupportedError.Code in getattr(
            excinfo.value, 'args', ())


# ---------------------------------------------------------------------------
# resolve_conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveConflict:

    async def test_resolve_conflict_applies_chosen_candidate(self, relink_mocks):
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.store.get.return_value = [
            {'new_external_id': 'NEW-A1', 'path': '/Root/A', 'name': 'A'},
            {'new_external_id': 'NEW-A2', 'path': '/Root/A', 'name': 'A'},
        ]
        relink_mocks.aget_by_id.return_value = _dept(
            id=5, external_id='OLD', tenant_id=2)

        applied = await DepartmentRelinkService.resolve_conflict(
            dept_id=5, chosen_new_external_id='NEW-A2')

        assert applied.new_external_id == 'NEW-A2'
        relink_mocks.aupdate_external_id.assert_awaited_once_with(
            5, 'NEW-A2')
        relink_mocks.store.delete.assert_awaited_once_with(5)
        relink_mocks.ainsert_v2.assert_awaited_once()
        audit_kwargs = relink_mocks.ainsert_v2.await_args.kwargs
        assert audit_kwargs['action'] == 'dept.relink_resolved'
        assert audit_kwargs['metadata']['strategy'] == 'manual_resolve'
        assert audit_kwargs['tenant_id'] == 2

    async def test_resolve_conflict_raises_19316_when_not_in_candidates(
        self, relink_mocks,
    ):
        from bisheng.org_sync.domain.services.relink_service import (
            DepartmentRelinkService,
        )
        relink_mocks.store.get.return_value = [
            {'new_external_id': 'NEW-A1'},
        ]
        with pytest.raises(Exception) as excinfo:
            await DepartmentRelinkService.resolve_conflict(
                dept_id=5, chosen_new_external_id='NEW-X')
        assert str(SsoRelinkConflictUnresolvedError.Code) in str(
            excinfo.value) or SsoRelinkConflictUnresolvedError.Code in getattr(
            excinfo.value, 'args', ())
        relink_mocks.aupdate_external_id.assert_not_awaited()
        relink_mocks.store.delete.assert_not_awaited()
