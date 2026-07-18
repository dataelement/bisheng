"""Tests for `_can_open_user_group_management` admitting Child Admin (tenant admin).

PRD §4.5 + F003 routing: a tenant admin (Child Admin) can enter the user
group management section. Tenant-isolated listing of groups is tracked
under v2.5.1 / F023.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.user_group.domain.services import user_group_service as m


def _user(user_id=10, user_role=None):
    return SimpleNamespace(
        user_id=user_id,
        user_role=user_role if user_role is not None else [2],
    )


@pytest.mark.asyncio
async def test_can_open_admits_sys_admin():
    assert await m._can_open_user_group_management(_user(user_role=[1])) is True


@pytest.mark.asyncio
async def test_can_open_admits_dept_admin():
    with patch.object(
        m, '_is_department_admin',
        new_callable=AsyncMock, return_value=True,
    ):
        assert await m._can_open_user_group_management(_user()) is True


@pytest.mark.asyncio
async def test_can_open_admits_tenant_admin():
    """Child Admin via tenant#admin → access permitted."""
    with patch.object(
        m, '_is_department_admin',
        new_callable=AsyncMock, return_value=False,
    ), patch(
        'bisheng.department.domain.services.department_service._is_tenant_admin',
        new_callable=AsyncMock, return_value=True,
    ):
        assert await m._can_open_user_group_management(_user()) is True


@pytest.mark.asyncio
async def test_can_open_rejects_plain_user():
    with patch.object(
        m, '_is_department_admin',
        new_callable=AsyncMock, return_value=False,
    ), patch(
        'bisheng.department.domain.services.department_service._is_tenant_admin',
        new_callable=AsyncMock, return_value=False,
    ):
        assert await m._can_open_user_group_management(_user()) is False
