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
    user.get_visible_tenants = AsyncMock(return_value=[1])
    user.has_tenant_admin = AsyncMock(return_value=False)
    return user


@pytest.fixture
def mock_login_user_normal():
    """Mock normal LoginUser."""
    user = MagicMock()
    user.user_id = 2
    user.is_admin.return_value = False
    user.get_visible_tenants = AsyncMock(return_value=[1])
    user.has_tenant_admin = AsyncMock(return_value=False)
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

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
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

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
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

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
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

        with patch.object(PermissionService, '_get_fga', return_value=None):
            result = await PermissionService.check(
                user_id=2, relation='viewer', object_type='workflow', object_id='abc',
                login_user=mock_login_user_normal,
            )
        # Falls back to _sync_owner_fallback which should return False for missing flow
        assert result is False

    @pytest.mark.asyncio
    async def test_check_knowledge_library_accepts_legacy_knowledge_space_tuple(
        self, mock_fga, mock_login_user_normal,
    ):
        from bisheng.permission.domain.services.permission_service import PermissionService

        await mock_fga.write_tuples(
            writes=[{'user': 'user:2', 'relation': 'viewer', 'object': 'knowledge_space:123'}],
        )

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=['knowledge_space']), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_check', new_callable=AsyncMock, return_value=None), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_check', new_callable=AsyncMock), \
             patch.object(PermissionService, '_get_resource_creator', new_callable=AsyncMock, return_value=None):
            result = await PermissionService.check(
                user_id=2, relation='viewer', object_type='knowledge_library', object_id='123',
                login_user=mock_login_user_normal,
            )

        assert result is True


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

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_finalize_accessible_ids',
                          new_callable=AsyncMock, side_effect=lambda ids, *_args, **_kwargs: ids):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_list_objects', new_callable=AsyncMock, return_value=None):
                with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_list_objects', new_callable=AsyncMock):
                    result = await PermissionService.list_accessible_ids(
                        user_id=2, relation='viewer', object_type='workflow',
                        login_user=mock_login_user_normal,
                    )
        assert sorted(result) == ['abc', 'def']

    @pytest.mark.asyncio
    async def test_knowledge_library_list_unions_legacy_ids(self, mock_fga, mock_login_user_normal):
        from bisheng.permission.domain.services.permission_service import PermissionService

        await mock_fga.write_tuples(writes=[
            {'user': 'user:2', 'relation': 'viewer', 'object': 'knowledge_library:abc'},
            {'user': 'user:2', 'relation': 'viewer', 'object': 'knowledge_space:def'},
        ])

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_finalize_accessible_ids',
                          new_callable=AsyncMock, side_effect=lambda ids, *_args, **_kwargs: ids), \
             patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=['knowledge_space']), \
             patch.object(PermissionService, '_filter_legacy_alias_ids', new_callable=AsyncMock, return_value=['def']), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_list_objects', new_callable=AsyncMock, return_value=None), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_list_objects', new_callable=AsyncMock):
            result = await PermissionService.list_accessible_ids(
                user_id=2, relation='viewer', object_type='knowledge_library',
                login_user=mock_login_user_normal,
            )

        assert sorted(result) == ['abc', 'def']

    @pytest.mark.asyncio
    async def test_fga_unavailable_still_returns_creator_owned_ids(self, mock_login_user_normal):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=None), \
             patch.object(PermissionService, '_resource_ids_by_creator_user_ids',
                          new_callable=AsyncMock, return_value=['wf-owned']), \
             patch.object(PermissionService, '_resource_ids_implicit_dept_admin_scope',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_resource_ids_child_tenant_admin_scope',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_filter_ids_by_tenant_gate',
                          new_callable=AsyncMock, return_value=['wf-owned']), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_list_objects',
                   new_callable=AsyncMock, return_value=None), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_list_objects',
                   new_callable=AsyncMock):
            result = await PermissionService.list_accessible_ids(
                user_id=2, relation='viewer', object_type='workflow',
                login_user=mock_login_user_normal,
            )

        assert result == ['wf-owned']


class TestPermissionServiceAuthorize:

    @pytest.mark.asyncio
    async def test_authorize_user_grant(self, mock_fga):
        """Grant viewer to user → write tuple."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
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

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            with patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user', new_callable=AsyncMock):
                await PermissionService.authorize(
                    object_type='workflow',
                    object_id='abc',
                    revokes=[AuthorizeRevokeItem(
                        subject_type='user', subject_id=5, relation='viewer',
                    )],
                )

        mock_fga.assert_tuple_count(0)

    @pytest.mark.asyncio
    async def test_authorize_knowledge_library_dual_writes_legacy_knowledge_space(self, mock_fga):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=['knowledge_space']), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user', new_callable=AsyncMock):
            await PermissionService.authorize(
                object_type='knowledge_library',
                object_id='abc',
                grants=[AuthorizeGrantItem(
                    subject_type='user', subject_id=5, relation='viewer',
                )],
            )

        mock_fga.assert_tuple_exists('user:5', 'viewer', 'knowledge_library:abc')
        mock_fga.assert_tuple_exists('user:5', 'viewer', 'knowledge_space:abc')

    @pytest.mark.asyncio
    async def test_authorize_department_invalidates_expanded_users(self, mock_fga):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(
                 PermissionService,
                 '_expand_subject',
                 new_callable=AsyncMock,
                 return_value=['department:5#member'],
             ), \
             patch.object(
                 PermissionService,
                 '_affected_user_ids_for_subject',
                 new_callable=AsyncMock,
                 return_value={8, 9},
             ), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user',
                   new_callable=AsyncMock) as invalidate_user:
            await PermissionService.authorize(
                object_type='workflow',
                object_id='abc',
                grants=[AuthorizeGrantItem(
                    subject_type='department', subject_id=5, relation='viewer',
                )],
            )

        invalidate_user.assert_any_await(8)
        invalidate_user.assert_any_await(9)
        assert invalidate_user.await_count == 2

    @pytest.mark.asyncio
    async def test_authorize_department_with_children_writes_subtree_tuples(self, mock_fga):
        """Department grants with include_children=True must write every subtree department."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(
                 PermissionService,
                 '_expand_subject',
                 new_callable=AsyncMock,
                 return_value=['department:5#member', 'department:6#member', 'department:7#member'],
             ), \
             patch.object(
                 PermissionService,
                 '_affected_user_ids_for_subject',
                 new_callable=AsyncMock,
                 return_value=set(),
             ), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user',
                   new_callable=AsyncMock):
            await PermissionService.authorize(
                object_type='knowledge_space',
                object_id='space-1',
                grants=[AuthorizeGrantItem(
                    subject_type='department',
                    subject_id=5,
                    relation='viewer',
                    include_children=True,
                )],
                enforce_fga_success=True,
            )

        mock_fga.assert_tuple_exists('department:5#member', 'viewer', 'knowledge_space:space-1')
        mock_fga.assert_tuple_exists('department:6#member', 'viewer', 'knowledge_space:space-1')
        mock_fga.assert_tuple_exists('department:7#member', 'viewer', 'knowledge_space:space-1')

    @pytest.mark.asyncio
    async def test_authorize_user_group_invalidates_group_users(self, mock_fga):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(
                 PermissionService,
                 '_affected_user_ids_for_subject',
                 new_callable=AsyncMock,
                 return_value={18, 19, 20},
             ), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user',
                   new_callable=AsyncMock) as invalidate_user:
            await PermissionService.authorize(
                object_type='workflow',
                object_id='abc',
                grants=[AuthorizeGrantItem(
                    subject_type='user_group', subject_id=7, relation='viewer',
                )],
            )

        invalidate_user.assert_any_await(18)
        invalidate_user.assert_any_await(19)
        invalidate_user.assert_any_await(20)
        assert invalidate_user.await_count == 3


class TestPermissionServiceCreatorFallback:

    @pytest.mark.asyncio
    async def test_get_resource_creator_assistant_uses_assistant_dao(self):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch('bisheng.database.models.flow.FlowDao.aget_flow_by_id',
                   new_callable=AsyncMock, return_value=None) as flow_lookup, \
             patch('bisheng.database.models.assistant.AssistantDao.aget_one_assistant',
                   new_callable=AsyncMock, return_value=MagicMock(user_id=12)) as assistant_lookup:
            result = await PermissionService._get_resource_creator('assistant', 'asst-1')

        assert result == 12
        flow_lookup.assert_not_awaited()
        assistant_lookup.assert_awaited_once_with('asst-1')

    @pytest.mark.asyncio
    async def test_get_resource_creator_tool_uses_tool_type_owner(self):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch('bisheng.tool.domain.models.gpts_tools.GptsToolsDao.aget_one_tool_type',
                   new_callable=AsyncMock, return_value=MagicMock(user_id=34)) as tool_lookup:
            result = await PermissionService._get_resource_creator('tool', '99')

        assert result == 34
        tool_lookup.assert_awaited_once_with(99)


class TestPermissionServiceBatchWrite:

    @pytest.mark.asyncio
    async def test_batch_write_success(self, mock_fga):
        """batch_write_tuples writes to FGA."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = [
            TupleOperation(action='write', user='user:1', relation='member', object='department:5'),
            TupleOperation(action='write', user='user:2', relation='member', object='department:5'),
        ]

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga):
            await PermissionService.batch_write_tuples(ops)

        mock_fga.assert_tuple_count(2)

    @pytest.mark.asyncio
    async def test_batch_write_fga_unavailable_saves_failed(self):
        """FGA unavailable → saves to FailedTuple."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        ops = [
            TupleOperation(action='write', user='user:1', relation='member', object='department:5'),
        ]

        with patch.object(PermissionService, '_get_fga', return_value=None):
            with patch.object(PermissionService, '_save_failed_tuples', new_callable=AsyncMock) as mock_save:
                await PermissionService.batch_write_tuples(ops)
                mock_save.assert_called_once()
                assert len(mock_save.call_args[0][0]) == 1


class TestPermissionServiceGetPermissionLevel:

    @pytest.mark.asyncio
    async def test_knowledge_library_permission_level_uses_legacy_knowledge_space_tuples(
        self, mock_fga, mock_login_user_normal,
    ):
        from bisheng.permission.domain.services.permission_service import PermissionService

        await mock_fga.write_tuples(
            writes=[{'user': 'user:2', 'relation': 'can_edit', 'object': 'knowledge_space:42'}],
        )

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=['knowledge_space']), \
             patch.object(PermissionService, '_get_resource_creator', new_callable=AsyncMock, return_value=None):
            result = await PermissionService.get_permission_level(
                user_id=2,
                object_type='knowledge_library',
                object_id='42',
                login_user=mock_login_user_normal,
            )

        assert result == 'can_edit'


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
