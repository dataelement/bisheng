"""Unit tests for PermissionService (T14 — test_permission_service).

Tests the five-level permission check chain, authorize with department expansion,
batch_write_tuples, and FailedTuple compensation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from test.fixtures.mock_openfga import InMemoryOpenFGAClient
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation


@pytest.fixture
def mock_fga():
    """In-memory FGA client."""
    return InMemoryOpenFGAClient()


@pytest.fixture
def mock_login_user_admin():
    """Mock admin LoginUser."""
    user = MagicMock()
    user.user_id = 1
    user.is_admin.return_value = True
    return user


@pytest.fixture
def mock_login_user_normal():
    """Mock normal LoginUser."""
    user = MagicMock()
    user.user_id = 2
    user.is_admin.return_value = False
    return user


class TestPermissionServiceCheck:

    @pytest.mark.asyncio
    async def test_admin_shortcircuit(self, mock_login_user_admin):
        """L1: Admin always returns True without FGA call."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        result = await PermissionService.check(
            user_id=1, relation='viewer', object_type='workflow', object_id='abc',
            login_user=mock_login_user_admin,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_fga_check_allowed(self, mock_fga, mock_login_user_normal):
        """L3: FGA returns True."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        # Pre-populate FGA
        await mock_fga.write_tuples(
            writes=[{'user': 'user:2', 'relation': 'viewer', 'object': 'workflow:abc'}],
        )

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_check', new_callable=AsyncMock, return_value=None):
                with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_check', new_callable=AsyncMock):
                    result = await PermissionService.check(
                        user_id=2, relation='viewer', object_type='workflow', object_id='abc',
                        login_user=mock_login_user_normal,
                    )
        assert result is True

    @pytest.mark.asyncio
    async def test_fga_check_denied_no_owner(self, mock_fga, mock_login_user_normal):
        """L3+L4: FGA returns False, no owner fallback."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_check', new_callable=AsyncMock, return_value=None):
                with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_check', new_callable=AsyncMock):
                    with patch.object(PermissionService, '_get_resource_creator', new_callable=AsyncMock, return_value=None):
                        result = await PermissionService.check(
                            user_id=2, relation='viewer', object_type='workflow', object_id='abc',
                            login_user=mock_login_user_normal,
                        )
        assert result is False

    @pytest.mark.asyncio
    async def test_owner_fallback(self, mock_fga, mock_login_user_normal):
        """L4: FGA returns False but user is DB creator → True."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_check', new_callable=AsyncMock, return_value=None):
                with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_check', new_callable=AsyncMock):
                    with patch.object(PermissionService, '_get_resource_creator', new_callable=AsyncMock, return_value=2):
                        result = await PermissionService.check(
                            user_id=2, relation='viewer', object_type='workflow', object_id='abc',
                            login_user=mock_login_user_normal,
                        )
        assert result is True

    @pytest.mark.asyncio
    async def test_fga_unavailable_fail_closed(self, mock_login_user_normal):
        """L5: FGA connection error → deny access."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga_client', return_value=None):
            result = await PermissionService.check(
                user_id=2, relation='viewer', object_type='workflow', object_id='abc',
                login_user=mock_login_user_normal,
            )
        # Falls back to _sync_owner_fallback which should return False for missing flow
        assert result is False


class TestPermissionServiceListAccessible:

    @pytest.mark.asyncio
    async def test_admin_returns_none(self, mock_login_user_admin):
        """Admin returns None (no filtering)."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        result = await PermissionService.list_accessible_ids(
            user_id=1, relation='viewer', object_type='workflow',
            login_user=mock_login_user_admin,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_normal_user_returns_ids(self, mock_fga, mock_login_user_normal):
        """Normal user returns list of IDs."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        await mock_fga.write_tuples(writes=[
            {'user': 'user:2', 'relation': 'viewer', 'object': 'workflow:abc'},
            {'user': 'user:2', 'relation': 'viewer', 'object': 'workflow:def'},
        ])

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_list_objects', new_callable=AsyncMock, return_value=None):
                with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_list_objects', new_callable=AsyncMock):
                    result = await PermissionService.list_accessible_ids(
                        user_id=2, relation='viewer', object_type='workflow',
                        login_user=mock_login_user_normal,
                    )
        assert sorted(result) == ['abc', 'def']


class TestPermissionServiceAuthorize:

    @pytest.mark.asyncio
    async def test_authorize_user_grant(self, mock_fga):
        """Grant viewer to user → write tuple."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user', new_callable=AsyncMock):
                await PermissionService.authorize(
                    object_type='workflow',
                    object_id='abc',
                    grants=[AuthorizeGrantItem(
                        subject_type='user', subject_id=5, relation='viewer',
                    )],
                )

        mock_fga.assert_tuple_exists('user:5', 'viewer', 'workflow:abc')

    @pytest.mark.asyncio
    async def test_authorize_revoke(self, mock_fga):
        """Revoke viewer from user."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        # Pre-populate
        await mock_fga.write_tuples(
            writes=[{'user': 'user:5', 'relation': 'viewer', 'object': 'workflow:abc'}],
        )

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user', new_callable=AsyncMock):
                await PermissionService.authorize(
                    object_type='workflow',
                    object_id='abc',
                    revokes=[AuthorizeRevokeItem(
                        subject_type='user', subject_id=5, relation='viewer',
                    )],
                )

        mock_fga.assert_tuple_count(0)


class TestPermissionServiceBatchWrite:

    @pytest.mark.asyncio
    async def test_batch_write_success(self, mock_fga):
        """batch_write_tuples writes to FGA."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = [
            TupleOperation(action='write', user='user:1', relation='member', object='department:5'),
            TupleOperation(action='write', user='user:2', relation='member', object='department:5'),
        ]

        with patch.object(PermissionService, '_get_fga_client', return_value=mock_fga):
            await PermissionService.batch_write_tuples(ops)

        mock_fga.assert_tuple_count(2)

    @pytest.mark.asyncio
    async def test_batch_write_fga_unavailable_saves_failed(self):
        """FGA unavailable → saves to FailedTuple."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = [
            TupleOperation(action='write', user='user:1', relation='member', object='department:5'),
        ]

        with patch.object(PermissionService, '_get_fga_client', return_value=None):
            with patch.object(PermissionService, '_save_failed_tuples', new_callable=AsyncMock) as mock_save:
                await PermissionService.batch_write_tuples(ops)
                mock_save.assert_called_once()
                assert len(mock_save.call_args[0][0]) == 1


class TestExpandSubject:

    @pytest.mark.asyncio
    async def test_expand_user(self):
        from bisheng.permission.domain.services.permission_service import PermissionService
        result = await PermissionService._expand_subject('user', 42)
        assert result == ['user:42']

    @pytest.mark.asyncio
    async def test_expand_user_group(self):
        from bisheng.permission.domain.services.permission_service import PermissionService
        result = await PermissionService._expand_subject('user_group', 10)
        assert result == ['user_group:10#member']

    @pytest.mark.asyncio
    async def test_expand_department_no_children(self):
        from bisheng.permission.domain.services.permission_service import PermissionService
        result = await PermissionService._expand_subject('department', 5, include_children=False)
        assert result == ['department:5#member']

    @pytest.mark.asyncio
    async def test_expand_department_with_children(self):
        """Expand department including subtree."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        mock_dept = MagicMock()
        mock_dept.path = '/1/5/'

        with patch('bisheng.database.models.department.DepartmentDao.aget_by_id', new_callable=AsyncMock, return_value=mock_dept):
            with patch('bisheng.database.models.department.DepartmentDao.aget_subtree_ids', new_callable=AsyncMock, return_value=[5, 6, 7]):
                result = await PermissionService._expand_subject('department', 5, include_children=True)

        assert sorted(result) == ['department:5#member', 'department:6#member', 'department:7#member']
