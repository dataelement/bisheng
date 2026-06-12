"""Unit tests for apurge_department — physical deletion of archived departments."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_admin_user():
    user = MagicMock()
    user.user_id = 1
    user.is_admin.return_value = True
    user.user_role = [1]
    user.tenant_id = 1
    return user


def _make_dept(dept_id='BS@test', internal_id=10, status='archived', parent_id=1):
    dept = MagicMock()
    dept.id = internal_id
    dept.dept_id = dept_id
    dept.status = status
    dept.parent_id = parent_id
    return dept


class TestApurgeDepartment:

    @pytest.mark.asyncio
    async def test_rejects_non_archived_department(self, mock_admin_user):
        """Only archived departments can be purged."""
        from bisheng.common.errcode.department import DepartmentNotArchivedError

        active_dept = _make_dept(status='active')

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
        ) as mock_session_ctx, \
             patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock, return_value=active_dept,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_ctx.return_value = mock_session

            from bisheng.department.domain.services.department_service import DepartmentService
            with pytest.raises(DepartmentNotArchivedError):
                await DepartmentService.apurge_department('BS@test', mock_admin_user)

    @pytest.mark.asyncio
    async def test_purge_deletes_roles_and_department(self, mock_admin_user):
        """Purge deletes scoped roles, UserDepartment records, and the department itself."""
        archived_dept = _make_dept(status='archived')

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
        ) as mock_session_ctx, \
             patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock, return_value=archived_dept,
        ), \
             patch(
            'bisheng.department.domain.services.department_service.DepartmentChangeHandler',
        ) as mock_handler, \
             patch(
            'bisheng.department.domain.services.department_service.delete',
        ), \
             patch(
            'bisheng.department.domain.services.department_service.select',
        ), \
             patch(
            'bisheng.core.openfga.manager.aget_fga_client',
            new_callable=AsyncMock, return_value=None,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_exec_result = MagicMock()
            mock_exec_result.all.return_value = []
            mock_exec_result.first.return_value = None
            mock_exec_result.one.return_value = 0
            mock_session.exec = AsyncMock(return_value=mock_exec_result)
            mock_session_ctx.return_value = mock_session

            mock_handler.on_purged.return_value = []
            mock_handler.execute_async = AsyncMock()

            from bisheng.department.domain.services.department_service import DepartmentService
            await DepartmentService.apurge_department('BS@test', mock_admin_user)

            mock_session.delete.assert_called_once_with(archived_dept)
            mock_session.commit.assert_called_once()
            mock_handler.on_purged.assert_called_once_with(10, [], [])

    @pytest.mark.asyncio
    async def test_purge_blocks_if_children_exist(self, mock_admin_user):
        """Purge rejects if any child departments still reference this one."""
        from bisheng.common.errcode.department import DepartmentHasChildrenError

        archived_dept = _make_dept(status='archived')
        child_dept = _make_dept(dept_id='BS@child', internal_id=20)

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
        ) as mock_session_ctx, \
             patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock, return_value=archived_dept,
        ), \
             patch(
            'bisheng.department.domain.services.department_service.select',
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_exec_result = MagicMock()
            mock_exec_result.first.return_value = child_dept
            mock_session.exec = AsyncMock(return_value=mock_exec_result)
            mock_session_ctx.return_value = mock_session

            from bisheng.department.domain.services.department_service import DepartmentService
            with pytest.raises(DepartmentHasChildrenError):
                await DepartmentService.apurge_department('BS@test', mock_admin_user)

    @pytest.mark.asyncio
    async def test_purge_blocks_if_members_exist(self, mock_admin_user):
        """Purge validates member references before deleting department rows."""
        from bisheng.common.errcode.department import DepartmentHasMembersError

        archived_dept = _make_dept(status='archived')

        with patch(
            'bisheng.department.domain.services.department_service.get_async_db_session',
        ) as mock_session_ctx, \
             patch(
            'bisheng.department.domain.services.department_service._get_dept_and_check_permission',
            new_callable=AsyncMock, return_value=archived_dept,
        ), \
             patch(
            'bisheng.department.domain.services.department_service.select',
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            no_child = MagicMock()
            no_child.first.return_value = None
            member_count = MagicMock()
            member_count.one.return_value = 1
            mock_session.exec = AsyncMock(side_effect=[no_child, member_count])
            mock_session_ctx.return_value = mock_session

            from bisheng.department.domain.services.department_service import DepartmentService
            with pytest.raises(DepartmentHasMembersError):
                await DepartmentService.apurge_department('BS@test', mock_admin_user)

            mock_session.delete.assert_not_called()
