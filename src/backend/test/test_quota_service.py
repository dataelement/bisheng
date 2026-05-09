"""Unit tests for QuotaService (T06 — F005-role-menu-quota).

Covers AC-15~AC-23: effective quota calculation, multi-role max,
tenant hard limit, admin unlimited, quota check enforcement.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_admin_user():
    user = MagicMock()
    user.user_id = 1
    user.is_admin.return_value = True
    user.tenant_id = 1
    return user


@pytest.fixture
def mock_normal_user():
    user = MagicMock()
    user.user_id = 10
    user.is_admin.return_value = False
    user.tenant_id = 1
    return user


def _make_role(role_id, quota_config=None):
    role = MagicMock()
    role.id = role_id
    role.quota_config = quota_config
    return role


def _make_user_role(role_id):
    ur = MagicMock()
    ur.role_id = role_id
    return ur


def _make_tenant(tenant_id=1, quota_config=None):
    t = MagicMock()
    t.id = tenant_id
    t.quota_config = quota_config
    return t


class TestGetEffectiveQuota:
    """AC-15~AC-19: effective quota calculation."""

    @pytest.mark.asyncio
    async def test_admin_returns_unlimited(self, mock_admin_user):
        """AC-19: Admin user always gets -1 (unlimited)."""
        from bisheng.role.domain.services.quota_service import QuotaService

        result = await QuotaService.get_effective_quota(
            user_id=1, resource_type='workflow', tenant_id=1,
            login_user=mock_admin_user,
        )
        assert result == -1

    @pytest.mark.asyncio
    async def test_multi_role_takes_max(self, mock_normal_user):
        """AC-17: Multi-role quota takes the maximum value (5, 10 → 10)."""
        from bisheng.role.domain.services.quota_service import QuotaService

        user_roles = [_make_user_role(3), _make_user_role(4)]
        roles = [
            _make_role(3, {'channel': 5}),
            _make_role(4, {'channel': 10}),
        ]
        tenant = _make_tenant(quota_config=None)  # tenant unlimited

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
            mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

            result = await QuotaService.get_effective_quota(
                user_id=10, resource_type='channel', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result == 10

    @pytest.mark.asyncio
    async def test_any_role_unlimited_returns_unlimited(self, mock_normal_user):
        """AC-16: If any role has -1 for a resource type, return -1."""
        from bisheng.role.domain.services.quota_service import QuotaService

        user_roles = [_make_user_role(3), _make_user_role(4)]
        roles = [
            _make_role(3, {'workflow': 10}),
            _make_role(4, {'workflow': -1}),
        ]

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
            mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=_make_tenant())

            result = await QuotaService.get_effective_quota(
                user_id=10, resource_type='workflow', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result == -1

    @pytest.mark.asyncio
    async def test_missing_key_uses_default(self, mock_normal_user):
        """AC-18: Missing quota_config key uses DEFAULT_ROLE_QUOTA."""
        from bisheng.role.domain.services.quota_service import QuotaService, DEFAULT_ROLE_QUOTA

        user_roles = [_make_user_role(3)]
        roles = [_make_role(3, {'channel': 5})]  # no 'knowledge_space' key
        tenant = _make_tenant(quota_config=None)

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
            mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

            result = await QuotaService.get_effective_quota(
                user_id=10, resource_type='knowledge_space', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result == DEFAULT_ROLE_QUOTA['knowledge_space']

    @pytest.mark.asyncio
    async def test_null_config_uses_default(self, mock_normal_user):
        """Role with quota_config=None uses all defaults."""
        from bisheng.role.domain.services.quota_service import QuotaService, DEFAULT_ROLE_QUOTA

        user_roles = [_make_user_role(3)]
        roles = [_make_role(3, None)]  # quota_config is None
        tenant = _make_tenant(quota_config=None)

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
            mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

            result = await QuotaService.get_effective_quota(
                user_id=10, resource_type='channel', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result == DEFAULT_ROLE_QUOTA['channel']

    @pytest.mark.asyncio
    async def test_no_roles_uses_default(self, mock_normal_user):
        """User with no roles uses DEFAULT_ROLE_QUOTA."""
        from bisheng.role.domain.services.quota_service import QuotaService, DEFAULT_ROLE_QUOTA

        tenant = _make_tenant(quota_config=None)

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=[])
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

            result = await QuotaService.get_effective_quota(
                user_id=10, resource_type='knowledge_space', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result == DEFAULT_ROLE_QUOTA['knowledge_space']

    @pytest.mark.asyncio
    async def test_tenant_limit_caps_role_quota(self, mock_normal_user):
        """AC-22: Tenant hard limit caps effective quota via min(remaining, role)."""
        from bisheng.role.domain.services.quota_service import QuotaService

        user_roles = [_make_user_role(3)]
        roles = [_make_role(3, {'knowledge_space': 30})]
        tenant = _make_tenant(quota_config={'knowledge_space': 50})  # tenant limit 50

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
            mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

            with patch.object(QuotaService, 'get_tenant_resource_count',
                              new_callable=AsyncMock, return_value=42):
                result = await QuotaService.get_effective_quota(
                    user_id=10, resource_type='knowledge_space', tenant_id=1,
                    login_user=mock_normal_user,
                )
        # tenant_remaining = 50 - 42 = 8, role_quota = 30
        # effective = min(8, 30) = 8
        assert result == 8

    @pytest.mark.asyncio
    async def test_tenant_unlimited_ignores_tenant(self, mock_normal_user):
        """Tenant with null quota_config means unlimited — only role_quota matters."""
        from bisheng.role.domain.services.quota_service import QuotaService

        user_roles = [_make_user_role(3)]
        roles = [_make_role(3, {'channel': 15})]
        tenant = _make_tenant(quota_config=None)

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao') as mock_ur_dao, \
             patch('bisheng.role.domain.services.quota_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.quota_service.TenantDao') as mock_tenant_dao:
            mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
            mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
            mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

            result = await QuotaService.get_effective_quota(
                user_id=10, resource_type='channel', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result == 15


class TestCheckQuota:
    """AC-20, AC-21: quota enforcement.

    F016 T04 rewired check_quota to call _apply_tenant_chain_cap directly
    (bypassing get_effective_quota) and raise 194xx subclasses instead of
    the v2.5.0 QuotaExceededError(24001). These two tests are updated to
    mock the new call target + assert the new exception class.
    """

    @pytest.mark.asyncio
    async def test_quota_exceeded_raises(self, mock_normal_user):
        """AC-20: TenantRoleQuotaExceededError(19402) when user_used >= effective."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantRoleQuotaExceededError

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(10, None))), \
             patch.object(QuotaService, 'get_user_resource_count',
                          new=AsyncMock(return_value=10)):
            with pytest.raises(TenantRoleQuotaExceededError):
                await QuotaService.check_quota(
                    user_id=10, resource_type='knowledge_space', tenant_id=1,
                    login_user=mock_normal_user,
                )

    @pytest.mark.asyncio
    async def test_quota_sufficient_returns_true(self, mock_normal_user):
        """AC-21: check_quota returns True when quota is sufficient."""
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(10, None))), \
             patch.object(QuotaService, 'get_user_resource_count',
                          new=AsyncMock(return_value=5)):
            result = await QuotaService.check_quota(
                user_id=10, resource_type='knowledge_space', tenant_id=1,
                login_user=mock_normal_user,
            )
        assert result is True


class TestKI01SqlTemplateSchema:
    """Regression for v2.5.0/F005 KI-01 (2026-04-19 fixed).

    Four SQL templates in ``_RESOURCE_COUNT_TEMPLATES`` referenced columns
    or tables that do not exist on any deployment; ``_count_resource``
    caught the MySQL error and returned 0, making quota counts silently
    wrong. Guard against re-introduction with static assertions — cheap
    and DB-free (full integration verified via 114 ``/quota/tree`` probe,
    see F016 ac-verification.md).
    """

    def test_knowledge_space_no_phantom_status_filter(self):
        from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES
        tmpl = _RESOURCE_COUNT_TEMPLATES['knowledge_space']
        assert 'status' not in tmpl.lower(), (
            f'knowledge table has no status column; template must not filter by it: {tmpl!r}'
        )

    def test_channel_no_phantom_status_filter(self):
        from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES
        for key in ('channel', 'channel_subscribe'):
            tmpl = _RESOURCE_COUNT_TEMPLATES[key]
            assert "status='active'" not in tmpl, (
                f'channel table has no status column; {key} template must not filter by it: {tmpl!r}'
            )

    def test_channel_subscribe_counts_memberships(self):
        from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES
        tmpl = _RESOURCE_COUNT_TEMPLATES['channel_subscribe']
        assert 'FROM space_channel_member' in tmpl
        assert 'INNER JOIN channel' in tmpl
        assert "scm.status IN ('ACTIVE','PENDING')" in tmpl
        assert '{qualified_col}' in tmpl

    def test_tool_uses_t_prefix_table_name(self):
        from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES
        tmpl = _RESOURCE_COUNT_TEMPLATES['tool']
        assert 'FROM t_gpts_tools' in tmpl, (
            f'actual table is t_gpts_tools (t_ prefix); template must use that: {tmpl!r}'
        )

    @pytest.mark.asyncio
    async def test_storage_count_preserves_fractional_gb(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        class _Result:
            def scalar(self):
                return int(1.5 * 1024 * 1024 * 1024)

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def execute(self, *args, **kwargs):
                return _Result()

        with patch('bisheng.core.database.get_async_db_session', return_value=_Session()):
            result = await QuotaService._count_resource('tenant_id', 1, 'storage_gb')

        assert result == 1.5


class TestValidateQuotaConfig:
    """AC-10c: quota_config validation."""

    def test_valid_config(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        QuotaService.validate_quota_config({'knowledge_space': 30, 'workflow': -1, 'channel': 0})

    def test_menu_approval_mode_bool_or_int(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        QuotaService.validate_quota_config({'channel': 10, 'menu_approval_mode': True})
        QuotaService.validate_quota_config({'channel': 10, 'menu_approval_mode': False})
        QuotaService.validate_quota_config({'menu_approval_mode': 0})
        QuotaService.validate_quota_config({'menu_approval_mode': 1})

    def test_menu_approval_mode_invalid_value(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.role import QuotaConfigInvalidError

        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'menu_approval_mode': 2})
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'menu_approval_mode': 'true'})

    def test_invalid_non_integer(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.role import QuotaConfigInvalidError

        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'knowledge_space': 'abc'})

    def test_invalid_negative_not_minus_one(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.role import QuotaConfigInvalidError

        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'knowledge_space': -5})

    def test_knowledge_space_file_one_decimal_gb(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        QuotaService.validate_quota_config({'knowledge_space_file': 0.1})
        QuotaService.validate_quota_config({'knowledge_space_file': 1.5})
        QuotaService.validate_quota_config({'knowledge_space_file': 999})
        QuotaService.validate_quota_config({'knowledge_space_file': 99999})
        QuotaService.validate_quota_config({'knowledge_space_file': -1})

    def test_knowledge_space_file_invalid_range_or_precision(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.role import QuotaConfigInvalidError

        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'knowledge_space_file': 0})
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'knowledge_space_file': 0.05})
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'knowledge_space_file': 100000})
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'knowledge_space_file': 1.55})

    def test_storage_gb_one_decimal_accepted(self):
        """storage_gb mirrors knowledge_space_file: -1 or 0.1~99999 with 1 decimal."""
        from bisheng.role.domain.services.quota_service import QuotaService

        QuotaService.validate_quota_config({'storage_gb': 0.1})
        QuotaService.validate_quota_config({'storage_gb': 1.5})
        QuotaService.validate_quota_config({'storage_gb': 100})
        QuotaService.validate_quota_config({'storage_gb': 999})
        QuotaService.validate_quota_config({'storage_gb': 1000})
        QuotaService.validate_quota_config({'storage_gb': 99999})
        QuotaService.validate_quota_config({'storage_gb': -1})

    def test_storage_gb_invalid_range_or_precision(self):
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.role import QuotaConfigInvalidError

        # 0 not allowed (0.1 minimum, mirrors knowledge_space_file)
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': 0})
        # below 0.1 GB
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': 0.05})
        # above 99999 GB
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': 100000})
        # more than 1 decimal place
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': 1.55})
        # negative (other than -1)
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': -2})
        # boolean is not a valid number
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': True})
        # string is not a number
        with pytest.raises(QuotaConfigInvalidError):
            QuotaService.validate_quota_config({'storage_gb': '1'})


def _make_tenant_obj(tenant_id, parent_tenant_id=None):
    t = MagicMock()
    t.id = tenant_id
    t.parent_tenant_id = parent_tenant_id
    return t


class TestGetStorageUsedGbBatch:
    """Bug 2: tenant management UI must show real used GB.

    Verifies the batch helper picks the correct counting path per row
    (root → aggregate, leaf → strict) and shares the SQL template with the
    quota interceptor (single source of truth, AC-04).
    """

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_dict(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        result = await QuotaService.get_storage_used_gb_batch([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_root_and_leaf_mixed_picks_correct_path(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        root = _make_tenant_obj(1, parent_tenant_id=None)
        leaf_a = _make_tenant_obj(7, parent_tenant_id=1)
        leaf_b = _make_tenant_obj(8, parent_tenant_id=1)

        with patch(
            'bisheng.database.models.tenant.TenantDao.aget_by_ids',
            new=AsyncMock(return_value=[root, leaf_a, leaf_b]),
        ), patch.object(
            QuotaService, '_aggregate_root_usage',
            new=AsyncMock(return_value=10.5),
        ) as agg, patch.object(
            QuotaService, '_count_usage_strict',
            new=AsyncMock(side_effect=[2.0, 0.0]),
        ) as strict:
            result = await QuotaService.get_storage_used_gb_batch([1, 7, 8])

        assert result == {1: 10.5, 7: 2.0, 8: 0.0}
        agg.assert_awaited_once_with(1, 'storage_gb')
        assert strict.await_count == 2

    @pytest.mark.asyncio
    async def test_missing_tenant_omitted_from_result(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch(
            'bisheng.database.models.tenant.TenantDao.aget_by_ids',
            new=AsyncMock(return_value=[]),
        ):
            result = await QuotaService.get_storage_used_gb_batch([99, 100])

        assert result == {}


class TestTenantStorageBytesHelpers:
    """Bug 1: write-path helpers used by KnowledgeSpaceService.add_file."""

    @pytest.mark.asyncio
    async def test_used_bytes_root_aggregates_children(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        root = _make_tenant_obj(1, parent_tenant_id=None)
        with patch(
            'bisheng.database.models.tenant.TenantDao.aget_by_id',
            new=AsyncMock(return_value=root),
        ), patch.object(
            QuotaService, '_aggregate_root_usage',
            new=AsyncMock(return_value=2.0),
        ), patch.object(
            QuotaService, '_count_usage_strict',
            new=AsyncMock(side_effect=AssertionError('leaf path must not run')),
        ):
            used = await QuotaService.get_tenant_storage_used_bytes(1)
        # 2 GB to bytes
        assert used == 2 * (1024 ** 3)

    @pytest.mark.asyncio
    async def test_used_bytes_leaf_uses_strict(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        leaf = _make_tenant_obj(5, parent_tenant_id=1)
        with patch(
            'bisheng.database.models.tenant.TenantDao.aget_by_id',
            new=AsyncMock(return_value=leaf),
        ), patch.object(
            QuotaService, '_count_usage_strict',
            new=AsyncMock(return_value=0.5),
        ), patch.object(
            QuotaService, '_aggregate_root_usage',
            new=AsyncMock(side_effect=AssertionError('root path must not run')),
        ):
            used = await QuotaService.get_tenant_storage_used_bytes(5)
        assert used == int(round(0.5 * (1024 ** 3)))

    @pytest.mark.asyncio
    async def test_used_bytes_unknown_tenant_returns_zero(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch(
            'bisheng.database.models.tenant.TenantDao.aget_by_id',
            new=AsyncMock(return_value=None),
        ):
            used = await QuotaService.get_tenant_storage_used_bytes(999)
        assert used == 0

    @pytest.mark.asyncio
    async def test_remaining_bytes_unlimited_returns_none(self):
        """No cap on the chain → None (unlimited)."""
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch.object(
            QuotaService, '_apply_tenant_chain_cap',
            new=AsyncMock(return_value=(-1, None)),
        ):
            assert await QuotaService.get_tenant_storage_remaining_bytes(5) is None

    @pytest.mark.asyncio
    async def test_remaining_bytes_returns_bytes(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch.object(
            QuotaService, '_apply_tenant_chain_cap',
            new=AsyncMock(return_value=(1.5, None)),
        ):
            remaining = await QuotaService.get_tenant_storage_remaining_bytes(5)
        assert remaining == int(round(1.5 * (1024 ** 3)))

    @pytest.mark.asyncio
    async def test_remaining_bytes_blocker_raises_19403(self):
        """Chain exhausted (any node remaining=0) → directly raises 19403."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError

        blocker = (5, 'tenant_limit', 1.0, 1.0, 'tenant-foo')
        with patch.object(
            QuotaService, '_apply_tenant_chain_cap',
            new=AsyncMock(return_value=(0, blocker)),
        ):
            with pytest.raises(TenantStorageQuotaExceededError) as exc_info:
                await QuotaService.get_tenant_storage_remaining_bytes(5)

        assert exc_info.value.Code == 19403
        assert exc_info.value.kwargs.get('used_gb') == 1.0
        assert exc_info.value.kwargs.get('quota_gb') == 1.0
        assert exc_info.value.kwargs.get('reason') == 'tenant_limit'
