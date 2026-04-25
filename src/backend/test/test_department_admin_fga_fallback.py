from contextlib import asynccontextmanager
from types import SimpleNamespace
import sys
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_department_admin_user_ids_falls_back_to_grant_table_when_fga_missing():
    from bisheng.department.domain.services.department_service import DepartmentService

    with patch(
        'bisheng.department.domain.services.department_service._aget_fga_client_with_fallback',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.department.domain.services.department_service.DepartmentAdminGrantDao.aget_user_ids_by_department',
        new_callable=AsyncMock,
        return_value=[7, 9],
    ) as grant_ids:
        result = await DepartmentService._aget_department_admin_user_ids(12)

    assert result == {7, 9}
    grant_ids.assert_awaited_once_with(12)


@pytest.mark.asyncio
async def test_get_department_admin_user_ids_falls_back_to_grant_table_when_fga_read_fails():
    from bisheng.department.domain.services.department_service import DepartmentService

    fake_fga = SimpleNamespace(read_tuples=AsyncMock(side_effect=RuntimeError('boom')))
    with patch(
        'bisheng.department.domain.services.department_service._aget_fga_client_with_fallback',
        new_callable=AsyncMock,
        return_value=fake_fga,
    ), patch(
        'bisheng.department.domain.services.department_service.DepartmentAdminGrantDao.aget_user_ids_by_department',
        new_callable=AsyncMock,
        return_value=[3],
    ) as grant_ids:
        result = await DepartmentService._aget_department_admin_user_ids(21)

    assert result == {3}
    grant_ids.assert_awaited_once_with(21)


@pytest.mark.asyncio
async def test_aset_admins_does_not_raise_when_fga_accessor_returns_none():
    from bisheng.department.domain.services import department_service as m

    dept = SimpleNamespace(id=5, status='active')
    login_user = SimpleNamespace(user_id=1)
    dummy_session = SimpleNamespace()
    fake_sync_memberships = AsyncMock()
    fake_department_ks_module = SimpleNamespace(
        DepartmentKnowledgeSpaceService=SimpleNamespace(
            sync_department_admin_memberships=fake_sync_memberships,
        ),
    )

    @asynccontextmanager
    async def fake_session():
        yield dummy_session

    with patch.object(
        m, 'get_async_db_session', fake_session,
    ), patch.object(
        m, '_get_dept_and_check_permission', new_callable=AsyncMock, return_value=dept,
    ), patch.object(
        m.DepartmentService, 'aget_admins', new_callable=AsyncMock, side_effect=[[], [{'user_id': 7, 'user_name': 'u7'}]],
    ) as aget_admins, patch(
        'bisheng.core.openfga.manager.aget_fga_client',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.core.openfga.manager.get_fga_client',
        return_value=None,
    ), patch.object(
        m.DepartmentChangeHandler, 'execute_async', new_callable=AsyncMock,
    ) as execute_async, patch.object(
        m.DepartmentAdminGrantDao, 'aupsert', new_callable=AsyncMock,
    ) as upsert, patch.dict(
        sys.modules,
        {'bisheng.knowledge.domain.services.department_knowledge_space_service': fake_department_ks_module},
    ):
        result = await m.DepartmentService.aset_admins('dept-5', [7], login_user)

    assert result == [{'user_id': 7, 'user_name': 'u7'}]
    aget_admins.assert_awaited()
    execute_async.assert_awaited_once()
    upsert.assert_awaited_once_with(7, 5, 'manual')
    fake_sync_memberships.assert_awaited_once_with(
        request=None,
        login_user=login_user,
        department_id=5,
        added_user_ids=[7],
        removed_user_ids=[],
    )
