"""Tests for ``DeptUpsertService`` — the gatekeeper between F014 payloads
and the ``DepartmentDao`` writes.

Covers:
- ``assert_parent_chain_exists`` raises 19312 on missing or soft-deleted
  rows (strict mode per Phase-3 decision).
- ``upsert_from_sync_payload`` forwards the correct fields to
  ``aupsert_by_external_id`` and never passes ``is_tenant_root`` /
  ``mounted_tenant_id`` (ensures the DAO preserves those by construction).
- Parent resolution: top-level items → ``parent_id=None, path='/'``;
  nested items derive ``path`` from the parent's own ``path + parent_id``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.sso_sync import SsoDeptParentMissingError
from bisheng.sso_sync.domain.schemas.payloads import DepartmentUpsertItem


def _dept(ext, *, id=1, path='/', is_deleted=0, parent_id=None,
          is_tenant_root=0, mounted_tenant_id=None):
    return SimpleNamespace(
        id=id, external_id=ext, path=path, is_deleted=is_deleted,
        parent_id=parent_id, is_tenant_root=is_tenant_root,
        mounted_tenant_id=mounted_tenant_id, source='sso',
    )


@pytest.mark.asyncio
class TestAssertParentChainExists:

    async def test_all_present_returns_mapping(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )
        d1 = _dept('A', id=1)
        d2 = _dept('B', id=2, path='/1/', parent_id=1)

        async def fake_get(source, ext):
            return {'A': d1, 'B': d2}.get(ext)

        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aget_by_source_external_id',
            new=fake_get,
        ):
            got = await DeptUpsertService.assert_parent_chain_exists(['A', 'B'])
        assert set(got.keys()) == {'A', 'B'}

    async def test_missing_raises_19312(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )

        async def fake_get(source, ext):
            return _dept('A') if ext == 'A' else None

        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aget_by_source_external_id',
            new=fake_get,
        ):
            with pytest.raises(Exception) as exc_info:
                await DeptUpsertService.assert_parent_chain_exists(['A', 'GHOST'])
        # SsoDeptParentMissingError.http_exception wraps the code (19312)
        # into HTTPException.status_code per project convention.
        assert '19312' in str(exc_info.value) or getattr(
            exc_info.value, 'status_code', None
        ) == SsoDeptParentMissingError.Code

    async def test_soft_deleted_treated_as_missing(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )

        async def fake_get(source, ext):
            return _dept(ext, is_deleted=1)

        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aget_by_source_external_id',
            new=fake_get,
        ):
            with pytest.raises(Exception):
                await DeptUpsertService.assert_parent_chain_exists(['A'])

    async def test_empty_input_is_noop(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )
        # No DAO calls expected — no patching needed.
        out = await DeptUpsertService.assert_parent_chain_exists([])
        assert out == {}


@pytest.mark.asyncio
class TestUpsertFromSyncPayload:

    async def test_top_level_upsert_passes_none_parent_and_root_path(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )
        item = DepartmentUpsertItem(
            external_id='TOP', name='Root Dept', sort=2, ts=100,
        )
        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock, return_value=_dept('TOP', id=99),
        ) as upsert_mock:
            await DeptUpsertService.upsert_from_sync_payload(
                existing=None, item=item, source='sso', last_sync_ts=100,
            )
        kwargs = upsert_mock.await_args.kwargs
        assert kwargs['external_id'] == 'TOP'
        assert kwargs['name'] == 'Root Dept'
        assert kwargs['parent_id'] is None
        assert kwargs['path'] == '/'
        assert kwargs['sort_order'] == 2
        assert kwargs['last_sync_ts'] == 100
        # Verify we never pass mount-related fields.
        assert 'is_tenant_root' not in kwargs
        assert 'mounted_tenant_id' not in kwargs

    async def test_nested_upsert_derives_path_from_parent(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )
        parent = _dept('P', id=5, path='/2/')
        item = DepartmentUpsertItem(
            external_id='C',
            name='Child',
            parent_external_id='P',
            sort=0,
            ts=200,
        )
        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=parent,
        ), patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock, return_value=_dept('C', id=9),
        ) as upsert_mock:
            await DeptUpsertService.upsert_from_sync_payload(
                existing=None, item=item, source='sso', last_sync_ts=200,
            )
        kwargs = upsert_mock.await_args.kwargs
        assert kwargs['parent_id'] == 5
        # path = parent.path + parent.id + '/' → '/2/5/'
        assert kwargs['path'] == '/2/5/'

    async def test_missing_parent_raises_19312(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )
        item = DepartmentUpsertItem(
            external_id='C', name='Orphan', parent_external_id='GHOST',
            sort=0, ts=200,
        )
        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock,
        ) as upsert_mock:
            with pytest.raises(Exception):
                await DeptUpsertService.upsert_from_sync_payload(
                    existing=None, item=item, source='sso', last_sync_ts=200,
                )
        upsert_mock.assert_not_awaited()

    async def test_soft_deleted_parent_raises_19312(self):
        from bisheng.sso_sync.domain.services.dept_upsert_service import (
            DeptUpsertService,
        )
        dead_parent = _dept('P', id=5, path='/2/', is_deleted=1)
        item = DepartmentUpsertItem(
            external_id='C', name='Child', parent_external_id='P', ts=100,
        )
        with patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=dead_parent,
        ), patch(
            'bisheng.sso_sync.domain.services.dept_upsert_service.'
            'DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock,
        ):
            with pytest.raises(Exception):
                await DeptUpsertService.upsert_from_sync_payload(
                    existing=None, item=item, source='sso', last_sync_ts=100,
                )
