"""Integration tests: ChangeHandler → PermissionService → OpenFGA (T14).

Tests that DepartmentChangeHandler and GroupChangeHandler execute_async()
correctly write tuples to OpenFGA via PermissionService.batch_write_tuples().
"""

import pytest
from unittest.mock import AsyncMock, patch

from test.fixtures.mock_openfga import InMemoryOpenFGAClient


@pytest.fixture
def mock_fga():
    return InMemoryOpenFGAClient()


class TestDepartmentChangeHandlerIntegration:

    @pytest.mark.asyncio
    async def test_on_created_writes_parent_tuple(self, mock_fga):
        from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = DepartmentChangeHandler.on_created(dept_id=5, parent_id=1)
        assert len(ops) == 1

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await DepartmentChangeHandler.execute_async(ops)

        mock_fga.assert_tuple_exists('department:1', 'parent', 'department:5')

    @pytest.mark.asyncio
    async def test_on_members_added_writes_member_tuples(self, mock_fga):
        from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = DepartmentChangeHandler.on_members_added(dept_id=5, user_ids=[10, 11, 12])
        assert len(ops) == 3

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await DepartmentChangeHandler.execute_async(ops)

        mock_fga.assert_tuple_count(3)
        mock_fga.assert_tuple_exists('user:10', 'member', 'department:5')
        mock_fga.assert_tuple_exists('user:11', 'member', 'department:5')
        mock_fga.assert_tuple_exists('user:12', 'member', 'department:5')

    @pytest.mark.asyncio
    async def test_on_moved_deletes_old_adds_new(self, mock_fga):
        from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        # Pre-populate old parent
        await mock_fga.write_tuples(
            writes=[{'user': 'department:1', 'relation': 'parent', 'object': 'department:5'}],
        )

        ops = DepartmentChangeHandler.on_moved(dept_id=5, old_parent_id=1, new_parent_id=2)

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await DepartmentChangeHandler.execute_async(ops)

        mock_fga.assert_tuple_count(1)
        mock_fga.assert_tuple_exists('department:2', 'parent', 'department:5')


class TestGroupChangeHandlerIntegration:

    @pytest.mark.asyncio
    async def test_on_created_writes_admin_tuple(self, mock_fga):
        from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = GroupChangeHandler.on_created(group_id=3, creator_user_id=1)
        assert len(ops) == 1

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await GroupChangeHandler.execute_async(ops)

        mock_fga.assert_tuple_exists('user:1', 'admin', 'user_group:3')

    @pytest.mark.asyncio
    async def test_on_members_added_writes_member_tuples(self, mock_fga):
        from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = GroupChangeHandler.on_members_added(group_id=3, user_ids=[10, 11])

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await GroupChangeHandler.execute_async(ops)

        mock_fga.assert_tuple_count(2)
        mock_fga.assert_tuple_exists('user:10', 'member', 'user_group:3')
        mock_fga.assert_tuple_exists('user:11', 'member', 'user_group:3')

    @pytest.mark.asyncio
    async def test_on_member_removed_deletes_tuple(self, mock_fga):
        from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        # Pre-populate
        await mock_fga.write_tuples(
            writes=[{'user': 'user:10', 'relation': 'member', 'object': 'user_group:3'}],
        )

        ops = GroupChangeHandler.on_member_removed(group_id=3, user_id=10)

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await GroupChangeHandler.execute_async(ops)

        mock_fga.assert_tuple_count(0)

    @pytest.mark.asyncio
    async def test_fga_unavailable_saves_failed_tuples(self):
        """When FGA is unavailable, operations saved to FailedTuple."""
        from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = GroupChangeHandler.on_created(group_id=3, creator_user_id=1)

        with patch.object(PermissionService, '_get_fga', return_value=None):
            with patch.object(PermissionService, '_save_failed_tuples', new_callable=AsyncMock) as mock_save:
                await GroupChangeHandler.execute_async(ops)
                mock_save.assert_called_once()
                saved_ops = mock_save.call_args[0][0]
                assert len(saved_ops) == 1
                assert saved_ops[0].user == 'user:1'
