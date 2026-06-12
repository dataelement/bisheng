from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _dept(dept_id, parent_id=None, limit=0):
    return SimpleNamespace(
        id=dept_id,
        parent_id=parent_id,
        concurrent_session_limit=limit,
    )


@pytest.mark.asyncio
async def test_resolve_limit_uses_nearest_limited_department():
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
    )

    login_user = SimpleNamespace(user_id=10)
    primary = SimpleNamespace(department_id=3)
    depts = {
        3: _dept(3, parent_id=2, limit=0),
        2: _dept(2, parent_id=1, limit=5),
        1: _dept(1, parent_id=None, limit=20),
    }

    with patch(
        'bisheng.department.domain.services.department_flow_service.'
        'UserDepartmentDao.aget_user_primary_department',
        AsyncMock(return_value=primary),
    ), patch(
        'bisheng.department.domain.services.department_flow_service.'
        'DepartmentDao.aget_by_id',
        AsyncMock(side_effect=lambda dept_id: depts.get(dept_id)),
    ):
        assert await DepartmentFlowService.resolve_limit_and_dept(login_user) == (5, 2)


@pytest.mark.asyncio
async def test_resolve_limit_without_primary_department_is_unlimited():
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
    )

    login_user = SimpleNamespace(user_id=10)
    with patch(
        'bisheng.department.domain.services.department_flow_service.'
        'UserDepartmentDao.aget_user_primary_department',
        AsyncMock(return_value=None),
    ):
        assert await DepartmentFlowService.resolve_limit_and_dept(login_user) == (0, None)


@pytest.mark.asyncio
async def test_slot_acquire_fails_open_when_redis_is_unavailable():
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
    )

    with patch(
        'bisheng.department.domain.services.department_flow_service.get_redis_client',
        AsyncMock(side_effect=RuntimeError('redis down')),
    ):
        assert await DepartmentFlowService.try_acquire_daily_chat_slot(2, 10, 1) is True
