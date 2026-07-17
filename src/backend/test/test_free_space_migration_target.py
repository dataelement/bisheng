from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.free_space_migration_service import (
    FreeSpaceMigrationService,
)


class _Dept:
    def __init__(self, id, path):
        self.id = id
        self.path = path


class _UserDept:
    def __init__(self, department_id):
        self.department_id = department_id


@pytest.mark.asyncio
async def test_no_primary_department_returns_none():
    with patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.UserDepartmentDao.aget_user_primary_department",
        new=AsyncMock(return_value=None),
    ):
        assert await FreeSpaceMigrationService.resolve_target_department_space(7) is None


@pytest.mark.asyncio
async def test_primary_department_bound_hits_directly():
    with patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.UserDepartmentDao.aget_user_primary_department",
        new=AsyncMock(return_value=_UserDept(3)),
    ), patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.DepartmentDao.aget_by_id",
        new=AsyncMock(return_value=_Dept(3, "/1/2/3/")),
    ), patch(
        "bisheng.knowledge.domain.services.free_space_migration_service."
        "DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=500),
    ):
        assert await FreeSpaceMigrationService.resolve_target_department_space(7) == 500


@pytest.mark.asyncio
async def test_walks_up_to_nearest_ancestor_binding():
    # 主部门 3 未绑定，父 2 未绑定，祖 1 绑定 → 命中最近的已绑定祖先(1)
    with patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.UserDepartmentDao.aget_user_primary_department",
        new=AsyncMock(return_value=_UserDept(3)),
    ), patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.DepartmentDao.aget_by_id",
        new=AsyncMock(return_value=_Dept(3, "/1/2/3/")),
    ), patch(
        "bisheng.knowledge.domain.services.free_space_migration_service."
        "DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=900),
    ):
        assert await FreeSpaceMigrationService.resolve_target_department_space(7) == 900


@pytest.mark.asyncio
async def test_no_binding_anywhere_returns_none():
    with patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.UserDepartmentDao.aget_user_primary_department",
        new=AsyncMock(return_value=_UserDept(3)),
    ), patch(
        "bisheng.knowledge.domain.services.free_space_migration_service.DepartmentDao.aget_by_id",
        new=AsyncMock(return_value=_Dept(3, "/1/2/3/")),
    ), patch(
        "bisheng.knowledge.domain.services.free_space_migration_service."
        "DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=None),
    ):
        assert await FreeSpaceMigrationService.resolve_target_department_space(7) is None
