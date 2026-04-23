"""Unit tests for PermissionService.get_resource_permissions() enrichment (T003).

Tests the FGA tuple parsing, name resolution, department merging, and edge cases.
"""

import pytest
from unittest.mock import AsyncMock, patch

from test.fixtures.mock_openfga import InMemoryOpenFGAClient
from bisheng.permission.domain.schemas.permission_schema import ResourcePermissionItem

from bisheng.user.domain.models.user import UserDao
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.group import GroupDao


@pytest.fixture
def mock_fga():
    """In-memory FGA client."""
    return InMemoryOpenFGAClient()


class TestEnrichPermissionTuples:
    """Test _enrich_permission_tuples directly."""

    @pytest.mark.asyncio
    async def test_parse_user_tuple(self):
        """Parse 'user:7' into subject_type='user', subject_id=7."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [{'user': 'user:7', 'relation': 'owner', 'object': 'workflow:1'}]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {('user', 7): 'Alice'}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 1
        assert result[0].subject_type == 'user'
        assert result[0].subject_id == 7
        assert result[0].subject_name == 'Alice'
        assert result[0].relation == 'owner'

    @pytest.mark.asyncio
    async def test_filter_department_member_tuple(self):
        """'department:5#member' should be filtered out (membership, not direct grant)."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [
            {'user': 'department:5#member', 'relation': 'viewer', 'object': 'workflow:1'},
        ]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_parse_department_direct_tuple(self):
        """'department:5' + relation='viewer' should be kept."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [{'user': 'department:5', 'relation': 'viewer', 'object': 'workflow:1'}]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {('department', 5): 'Engineering'}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 1
        assert result[0].subject_type == 'department'
        assert result[0].subject_id == 5
        assert result[0].subject_name == 'Engineering'
        assert result[0].relation == 'viewer'

    @pytest.mark.asyncio
    async def test_filter_user_group_member_tuple(self):
        """'user_group:3#member' should be filtered out."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [
            {'user': 'user_group:3#member', 'relation': 'editor', 'object': 'workflow:1'},
        ]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_parse_user_group_direct_tuple(self):
        """'user_group:3' + relation='editor' should be kept."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [{'user': 'user_group:3', 'relation': 'editor', 'object': 'workflow:1'}]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {('user_group', 3): 'Alpha Team'}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 1
        assert result[0].subject_type == 'user_group'
        assert result[0].subject_id == 3
        assert result[0].subject_name == 'Alpha Team'
        assert result[0].relation == 'editor'

    @pytest.mark.asyncio
    async def test_department_merge(self):
        """Same (dept_id, relation) with multiple tuples should merge to include_children=True."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [
            {'user': 'department:5', 'relation': 'viewer', 'object': 'workflow:1'},
            {'user': 'department:5', 'relation': 'viewer', 'object': 'workflow:1'},
        ]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {('department', 5): 'Engineering'}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 1
        assert result[0].include_children is True

    @pytest.mark.asyncio
    async def test_empty_tuples(self):
        """Empty FGA tuple list returns empty result."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        result = await PermissionService._enrich_permission_tuples([])
        assert result == []

    @pytest.mark.asyncio
    async def test_unknown_subject_type(self):
        """Unknown subject format should be silently skipped."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [
            {'user': 'unknown_type:99', 'relation': 'viewer', 'object': 'workflow:1'},
            {'user': 'malformed', 'relation': 'viewer', 'object': 'workflow:1'},
            {'user': '', 'relation': 'viewer', 'object': 'workflow:1'},
        ]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {}
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_mixed_subjects(self):
        """Mixed user/department/group tuples are all enriched correctly."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [
            {'user': 'user:1', 'relation': 'owner', 'object': 'knowledge_space:10'},
            {'user': 'user:2', 'relation': 'editor', 'object': 'knowledge_space:10'},
            {'user': 'department:5', 'relation': 'viewer', 'object': 'knowledge_space:10'},
            {'user': 'user_group:3', 'relation': 'manager', 'object': 'knowledge_space:10'},
            {'user': 'department:5#member', 'relation': 'viewer', 'object': 'knowledge_space:10'},
        ]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {
                ('user', 1): 'Admin',
                ('user', 2): 'Bob',
                ('department', 5): 'Engineering',
                ('user_group', 3): 'Alpha Team',
            }
            result = await PermissionService._enrich_permission_tuples(tuples)

        # department:5#member is filtered out
        assert len(result) == 4
        types = [(r.subject_type, r.subject_id) for r in result]
        assert ('user', 1) in types
        assert ('user', 2) in types
        assert ('department', 5) in types
        assert ('user_group', 3) in types

    @pytest.mark.asyncio
    async def test_name_not_found(self):
        """Subject whose name cannot be resolved gets subject_name=None."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        tuples = [{'user': 'user:999', 'relation': 'viewer', 'object': 'workflow:1'}]

        with patch.object(PermissionService, '_resolve_subject_names', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = {}  # user:999 not found
            result = await PermissionService._enrich_permission_tuples(tuples)

        assert len(result) == 1
        assert result[0].subject_name is None


class TestResolveSubjectNames:
    """Test _resolve_subject_names with mocked DAOs."""

    @pytest.mark.asyncio
    async def test_batch_name_resolution(self):
        """Batch-resolve user, department, and group names."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        mock_user = AsyncMock()
        mock_user.user_id = 7
        mock_user.user_name = 'Alice'

        mock_dept = AsyncMock()
        mock_dept.id = 5
        mock_dept.name = 'Engineering'

        mock_group = AsyncMock()
        mock_group.id = 3
        mock_group.group_name = 'Alpha Team'

        with patch.object(UserDao, 'aget_user_by_ids', new_callable=AsyncMock, return_value=[mock_user]), \
             patch.object(DepartmentDao, 'aget_by_ids', new_callable=AsyncMock, return_value=[mock_dept]), \
             patch.object(GroupDao, 'aget_group_by_ids', new_callable=AsyncMock, return_value=[mock_group]):

            result = await PermissionService._resolve_subject_names(
                user_ids=[7], dept_ids=[5], group_ids=[3],
            )

        assert result[('user', 7)] == 'Alice'
        assert result[('department', 5)] == 'Engineering'
        assert result[('user_group', 3)] == 'Alpha Team'

    @pytest.mark.asyncio
    async def test_empty_ids(self):
        """Empty ID lists should not call DAOs."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        result = await PermissionService._resolve_subject_names(
            user_ids=[], dept_ids=[], group_ids=[],
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_dao_failure_graceful(self):
        """DAO failure should not raise, just return partial results."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        mock_user = AsyncMock()
        mock_user.user_id = 7
        mock_user.user_name = 'Alice'

        with patch.object(UserDao, 'aget_user_by_ids', new_callable=AsyncMock, return_value=[mock_user]), \
             patch.object(DepartmentDao, 'aget_by_ids', new_callable=AsyncMock, side_effect=Exception('DB error')):

            result = await PermissionService._resolve_subject_names(
                user_ids=[7], dept_ids=[5], group_ids=[],
            )

        assert result[('user', 7)] == 'Alice'
        assert ('department', 5) not in result


class TestGetResourcePermissionsIntegration:
    """Integration test with mock FGA client."""

    @pytest.mark.asyncio
    async def test_full_flow(self, mock_fga):
        """Full enrichment flow: write tuples → read → enrich → verify."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        # Pre-populate FGA tuples
        await mock_fga.write_tuples(writes=[
            {'user': 'user:1', 'relation': 'owner', 'object': 'workflow:42'},
            {'user': 'user:2', 'relation': 'editor', 'object': 'workflow:42'},
        ])

        mock_user1 = AsyncMock()
        mock_user1.user_id = 1
        mock_user1.user_name = 'Admin'

        mock_user2 = AsyncMock()
        mock_user2.user_id = 2
        mock_user2.user_name = 'Bob'

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(UserDao, 'aget_user_by_ids', new_callable=AsyncMock, return_value=[mock_user1, mock_user2]):

            result = await PermissionService.get_resource_permissions(
                object_type='workflow', object_id='42',
            )

        assert len(result) == 2
        owner = next(r for r in result if r.relation == 'owner')
        assert owner.subject_name == 'Admin'
        editor = next(r for r in result if r.relation == 'editor')
        assert editor.subject_name == 'Bob'

    @pytest.mark.asyncio
    async def test_fga_unavailable(self):
        """FGA unreachable returns empty list."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        with patch.object(PermissionService, '_get_fga', return_value=None):
            result = await PermissionService.get_resource_permissions(
                object_type='workflow', object_id='42',
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_knowledge_library_permissions_merge_legacy_knowledge_space_tuples(self, mock_fga):
        """knowledge_library should still surface historical knowledge_space tuples."""
        from bisheng.permission.domain.services.permission_service import PermissionService

        await mock_fga.write_tuples(writes=[
            {'user': 'user:1', 'relation': 'owner', 'object': 'knowledge_space:42'},
        ])

        mock_user1 = AsyncMock()
        mock_user1.user_id = 1
        mock_user1.user_name = 'Admin'

        with patch.object(PermissionService, '_get_fga', return_value=mock_fga), \
             patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=['knowledge_space']), \
             patch.object(UserDao, 'aget_user_by_ids', new_callable=AsyncMock, return_value=[mock_user1]):
            result = await PermissionService.get_resource_permissions(
                object_type='knowledge_library', object_id='42',
            )

        assert len(result) == 1
        assert result[0].relation == 'owner'
        assert result[0].subject_name == 'Admin'
