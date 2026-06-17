"""Tests for ``SgDepartmentsSyncService`` — SG organization sync."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgDepartmentFieldItem,
    SgDepartmentSyncRequest,
)

MODULE = 'bisheng.sso_sync.domain.services.sg_departments_sync_service'


def _dept(*, dept_id: int = 100, path: str = '/1/100/'):
    return SimpleNamespace(id=dept_id, path=path)


def _request(*fields: SgDepartmentFieldItem, mdm_id: int = 42, uuid: str = 'batch-uuid'):
    return SgDepartmentSyncRequest(
        mdmId=mdm_id,
        BusinessSystem=1,
        uuid=uuid,
        Field=list(fields),
    )


@pytest.mark.asyncio
class TestSgDepartmentsSyncService:

    async def test_root_department_upsert_success(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid='u1', code='D1', remark='Engineering', state='0'),
        )
        with patch(
            f'{MODULE}.DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock,
        ) as upsert, patch(
            f'{MODULE}.DepartmentDao.aarchive_by_external_id',
            new_callable=AsyncMock,
        ) as archive:
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == '0'
        assert response.esb.desc == 'success'
        infos = response.esb.data.data_infos.data_info
        assert len(infos) == 1
        assert infos[0].status == '0'
        assert infos[0].code == 'D1'
        assert infos[0].version == '42'
        upsert.assert_awaited_once()
        archive.assert_not_awaited()

    async def test_child_department_resolves_parent_in_same_batch(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid='u1', code='P1', remark='Parent', state='0'),
            SgDepartmentFieldItem(
                uuid='u2', code='C1', pid='P1', remark='Child', state='0',
            ),
        )
        parent = _dept(dept_id=10, path='/1/10/')

        async def _upsert(**kwargs):
            if kwargs['external_id'] == 'P1':
                return parent
            return _dept(dept_id=11, path='/1/10/11/')

        with patch(
            f'{MODULE}.DepartmentDao.aget_by_external_id',
            new_callable=AsyncMock,
            side_effect=lambda ext, _tid: parent if ext == 'P1' else None,
        ), patch(
            f'{MODULE}.DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock,
            side_effect=_upsert,
        ):
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == '0'
        infos = response.esb.data.data_infos.data_info
        assert [one.code for one in infos] == ['P1', 'C1']
        assert all(one.status == '0' for one in infos)

    async def test_disabled_department_triggers_archive(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid='u1', code='D1', remark='Archived', state='1'),
        )
        with patch(
            f'{MODULE}.DepartmentDao.aupsert_by_external_id',
            new_callable=AsyncMock,
        ), patch(
            f'{MODULE}.DepartmentDao.aarchive_by_external_id',
            new_callable=AsyncMock,
        ) as archive:
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == '0'
        archive.assert_awaited_once()
        assert archive.await_args.args[:2] == ('sg', 'D1')

    async def test_missing_code_returns_row_failure(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(SgDepartmentFieldItem(uuid='u1', code=''))
        response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == '1'
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == '1'
        assert 'code is required' in info.error_text

    async def test_invalid_state_returns_row_failure(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid='u1', code='D1', state='9'),
        )
        response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == '1'
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == '1'
        assert 'state must be 0(enabled) or 1(disabled)' in info.error_text

    async def test_parent_not_found_marks_row_failed(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(
                uuid='u1', code='C1', pid='MISSING', remark='Child', state='0',
            ),
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_external_id',
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == '1'
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == '1'
        assert 'parent external_id=MISSING not found' in info.error_text
