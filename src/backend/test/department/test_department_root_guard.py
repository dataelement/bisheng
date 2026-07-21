"""Tests for canonical default root department guardrails."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.department import DepartmentDefaultRootMoveForbiddenError
from bisheng.department.domain.services.department_root_guard import (
    aassert_default_root_parent_immutable,
    aget_default_root_dept_id,
    ais_default_root_department,
)


@pytest.mark.asyncio
async def test_aget_default_root_dept_id_returns_tenant_pointer():
    tenant = MagicMock(root_dept_id=42)
    with patch(
        "bisheng.department.domain.services.department_root_guard.TenantDao.aget_by_id",
        new_callable=AsyncMock,
        return_value=tenant,
    ):
        assert await aget_default_root_dept_id(1) == 42


@pytest.mark.asyncio
async def test_aassert_default_root_parent_immutable_allows_other_departments():
    with patch(
        "bisheng.department.domain.services.department_root_guard.aget_default_root_dept_id",
        new_callable=AsyncMock,
        return_value=1,
    ):
        await aassert_default_root_parent_immutable(99, 2)


@pytest.mark.asyncio
async def test_aassert_default_root_parent_immutable_blocks_reparent():
    dept = MagicMock(id=1, parent_id=None, tenant_id=1)
    with (
        patch(
            "bisheng.department.domain.services.department_root_guard.aget_default_root_dept_id",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "bisheng.department.domain.services.department_root_guard.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            return_value=dept,
        ),
    ):
        with pytest.raises(DepartmentDefaultRootMoveForbiddenError):
            await aassert_default_root_parent_immutable(1, 5)


@pytest.mark.asyncio
async def test_aassert_default_root_parent_immutable_allows_noop():
    dept = MagicMock(id=1, parent_id=None, tenant_id=1)
    with (
        patch(
            "bisheng.department.domain.services.department_root_guard.aget_default_root_dept_id",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "bisheng.department.domain.services.department_root_guard.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            return_value=dept,
        ),
    ):
        await aassert_default_root_parent_immutable(1, None)


@pytest.mark.asyncio
async def test_ais_default_root_department():
    dept = MagicMock(id=7, tenant_id=1)
    with patch(
        "bisheng.department.domain.services.department_root_guard.aget_default_root_dept_id",
        new_callable=AsyncMock,
        return_value=7,
    ):
        assert await ais_default_root_department(dept) is True
