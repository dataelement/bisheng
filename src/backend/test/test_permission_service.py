"""Unit tests for PermissionService (T14 — test_permission_service).

Tests the five-level permission check chain, authorize with department expansion,
batch_write_tuples, and FailedTuple compensation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from test.fixtures.mock_openfga import InMemoryOpenFGAClient


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
    async def test_department_space_member_fallback_allows_read(self, mock_fga, mock_login_user_normal):
        """Department-bound knowledge spaces grant implicit read to exact department members."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_evaluate_tenant_gate', new_callable=AsyncMock, return_value=(False, None)), \
             patch.object(PermissionService, '_get_resource_creator', new_callable=AsyncMock, return_value=99), \
             patch.object(PermissionService, '_implicit_department_space_member_level',
                          new_callable=AsyncMock, return_value='can_read'), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_check',
                   new_callable=AsyncMock, return_value=None), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_check',
                   new_callable=AsyncMock):
            result = await PermissionService.check(
                user_id=2,
                relation='can_read',
                object_type='knowledge_space',
                object_id='101',
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
             patch.object(PermissionService, '_resource_ids_child_tenant_admin_scope',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_implicit_department_bound_space_ids',
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

    @pytest.mark.asyncio
    async def test_list_includes_spaces_granted_to_user_department(
        self, mock_fga, mock_login_user_normal,
    ):
        """Department grants must appear even without user→department FGA membership."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        await mock_fga.write_tuples(writes=[
            {'user': 'department:5#member', 'relation': 'can_read', 'object': 'knowledge_space:101'},
        ])

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_membership_list_subjects',
                          new_callable=AsyncMock, return_value=['department:5#member']), \
             patch.object(PermissionService, '_finalize_accessible_ids',
                          new_callable=AsyncMock, side_effect=lambda ids, *_args, **_kwargs: ids), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_list_objects',
                   new_callable=AsyncMock, return_value=None), \
             patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_list_objects',
                   new_callable=AsyncMock):
            result = await PermissionService.list_accessible_ids(
                user_id=2, relation='can_read', object_type='knowledge_space',
                login_user=mock_login_user_normal,
            )

        assert result == ['101']

    @pytest.mark.asyncio
    async def test_finalize_adds_implicit_department_bound_spaces(self, mock_login_user_normal):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_resource_ids_by_creator_user_ids',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_resource_ids_child_tenant_admin_scope',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_implicit_department_bound_space_ids',
                          new_callable=AsyncMock, return_value=['202']), \
             patch.object(PermissionService, '_filter_ids_by_tenant_gate',
                          new_callable=AsyncMock, side_effect=lambda _uid, _type, object_ids, _user=None: object_ids):
            result = await PermissionService._finalize_accessible_ids(
                [], 2, 'knowledge_space', login_user=mock_login_user_normal, relation='can_read',
            )

        assert result == ['202']

    @pytest.mark.asyncio
    async def test_finalize_skips_implicit_department_spaces_for_manage(self, mock_login_user_normal):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_resource_ids_by_creator_user_ids',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_resource_ids_child_tenant_admin_scope',
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(PermissionService, '_implicit_department_bound_space_ids',
                          new_callable=AsyncMock, return_value=['202']) as implicit, \
             patch.object(PermissionService, '_filter_ids_by_tenant_gate',
                          new_callable=AsyncMock, side_effect=lambda _uid, _type, object_ids, _user=None: object_ids):
            result = await PermissionService._finalize_accessible_ids(
                [], 2, 'knowledge_space', login_user=mock_login_user_normal, relation='can_manage',
            )

        assert result == []
        implicit.assert_not_awaited()


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

    @pytest.mark.parametrize('fga_enabled', [True, False])
    @pytest.mark.parametrize(
        ('user_id', 'expected'),
        [
            (12, False),
            (34, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_knowledge_file_fallback_uses_current_knowledge_creator(
        self,
        fga_enabled,
        user_id,
        expected,
        mock_fga,
        mock_login_user_normal,
    ):
        """File uploader attribution must not bypass the current space owner."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        file_record = MagicMock(id=77, user_id=12, knowledge_id=55)
        knowledge = MagicMock(id=55, user_id=34)
        fga = mock_fga if fga_enabled else None

        with patch.object(PermissionService, '_get_fga', return_value=fga), patch(
            'bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            return_value=[file_record],
        ), patch(
            'bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=knowledge,
        ), patch(
            'bisheng.permission.domain.services.permission_cache.PermissionCache.get_check',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.permission.domain.services.permission_cache.PermissionCache.set_check',
            new_callable=AsyncMock,
        ):
            result = await PermissionService.check(
                user_id=user_id,
                relation='can_delete',
                object_type='knowledge_file',
                object_id='77',
                login_user=mock_login_user_normal,
            )

        assert result is expected

    @pytest.mark.asyncio
    async def test_knowledge_file_fallback_fails_closed_when_knowledge_missing(self):
        from bisheng.permission.domain.services.permission_service import PermissionService

        file_record = MagicMock(id=77, user_id=12, knowledge_id=55)
        with patch(
            'bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            return_value=[file_record],
        ), patch(
            'bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=None,
        ) as knowledge_lookup:
            result = await PermissionService._get_resource_creator('knowledge_file', '77')

        assert result is None
        knowledge_lookup.assert_awaited_once_with(55)

    @pytest.mark.asyncio
    async def test_knowledge_file_fallback_fails_closed_when_lookup_errors(self):
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch(
            'bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.aget_file_by_ids',
            new_callable=AsyncMock,
            side_effect=RuntimeError('database unavailable'),
        ):
            result = await PermissionService._get_resource_creator('knowledge_file', '77')

        assert result is None

    @pytest.mark.asyncio
    async def test_knowledge_file_creator_owned_ids_follow_knowledge_creators(self):
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
        from bisheng.permission.domain.services.permission_service import PermissionService

        async def knowledge_ids_for_creator(user_id, knowledge_type):
            if user_id == 34 and knowledge_type == KnowledgeTypeEnum.SPACE:
                return [55]
            return []

        async def files_for_spaces(knowledge_ids):
            return [MagicMock(id=77)] if knowledge_ids == [55] else []

        with patch.object(
            KnowledgeDao,
            'aget_knowledge_ids_created_by',
            new_callable=AsyncMock,
            side_effect=knowledge_ids_for_creator,
        ), patch.object(
            KnowledgeFileDao,
            'aget_file_by_space_filters',
            new_callable=AsyncMock,
            side_effect=files_for_spaces,
        ) as file_lookup, patch(
            'bisheng.core.database.get_async_db_session',
            side_effect=AssertionError('must not use KnowledgeFile.user_id for creator lookup'),
        ):
            creator_result = await PermissionService._resource_ids_by_creator_user_ids(
                'knowledge_file', {34},
            )
            uploader_result = await PermissionService._resource_ids_by_creator_user_ids(
                'knowledge_file', {12},
            )

        assert creator_result == ['77']
        assert uploader_result == []
        assert [item.args[0] for item in file_lookup.await_args_list] == [[55], []]

    @pytest.mark.asyncio
    async def test_knowledge_file_permission_list_includes_fallback_owner(
        self,
    ):
        from bisheng.permission.api.endpoints.resource_permission import _add_creator_owner_entry
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(
            PermissionService,
            '_get_resource_creator',
            new_callable=AsyncMock,
            return_value=34,
        ):
            result = await _add_creator_owner_entry(
                resource_type='knowledge_file',
                resource_id='77',
                permissions=[],
                model_map={},
            )

        assert len(result) == 1
        assert result[0].subject_id == 34
        assert result[0].relation == 'owner'

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
