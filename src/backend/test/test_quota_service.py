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

    def test_tool_uses_t_prefix_table_name(self):
        from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES
        tmpl = _RESOURCE_COUNT_TEMPLATES['tool']
        assert 'FROM t_gpts_tools' in tmpl, (
            f'actual table is t_gpts_tools (t_ prefix); template must use that: {tmpl!r}'
        )


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
