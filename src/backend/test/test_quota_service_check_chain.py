"""Unit tests for F016 T04 — _apply_tenant_chain_cap + check_quota 194xx.

Covers AC-01 (tenant limit exceeded), AC-04 (storage 19403), AC-08 (Root
hardcap blocks Child with '集团总量已耗尽' msg variant). Uses mock+patch
style matching test_quota_service.py baseline.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_tenant(tenant_id, parent_tenant_id=None, quota_config=None, status='active'):
    t = MagicMock()
    t.id = tenant_id
    t.parent_tenant_id = parent_tenant_id
    t.quota_config = quota_config or {}
    t.status = status
    return t


def _make_non_admin_user(user_id=10):
    u = MagicMock()
    u.user_id = user_id
    u.is_admin.return_value = False
    u.tenant_id = 5
    return u


def _make_admin_user(user_id=1):
    u = MagicMock()
    u.user_id = user_id
    u.is_admin.return_value = True
    u.tenant_id = 1
    return u


class TestApplyTenantChainCap:
    """Core chain-cap computation: leaf + Root min with role_quota."""

    @pytest.mark.asyncio
    async def test_chain_cap_child_only_under_limit(self):
        """Child quota_config.knowledge_space=10, used=3 → remaining=7 min role=-1 → 7."""
        from bisheng.role.domain.services.quota_service import QuotaService

        child = _make_tenant(5, parent_tenant_id=1, quota_config={'knowledge_space': 10})
        root = _make_tenant(1, parent_tenant_id=None, quota_config=None)
        aget_map = {5: child, 1: root}

        with patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                   new=AsyncMock(side_effect=lambda tid: aget_map.get(tid))), \
             patch.object(QuotaService, '_count_usage_strict',
                          new=AsyncMock(return_value=3)), \
             patch.object(QuotaService, '_aggregate_root_usage',
                          new=AsyncMock(return_value=0)):
            effective, blocker = await QuotaService._apply_tenant_chain_cap(
                role_quota=-1, tenant_id=5, resource_type='knowledge_space',
            )

        assert effective == 7
        assert blocker is None

    @pytest.mark.asyncio
    async def test_chain_cap_child_exhausted_returns_tenant_limit_blocker(self):
        """AC-01: Child quota=2 used=2 → blocker=(5, 'tenant_limit')."""
        from bisheng.role.domain.services.quota_service import QuotaService

        child = _make_tenant(5, parent_tenant_id=1, quota_config={'knowledge_space': 2})
        root = _make_tenant(1, parent_tenant_id=None, quota_config=None)
        aget_map = {5: child, 1: root}

        with patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                   new=AsyncMock(side_effect=lambda tid: aget_map.get(tid))), \
             patch.object(QuotaService, '_count_usage_strict',
                          new=AsyncMock(return_value=2)):
            effective, blocker = await QuotaService._apply_tenant_chain_cap(
                role_quota=-1, tenant_id=5, resource_type='knowledge_space',
            )

        assert effective == 0
        assert blocker == (5, 'tenant_limit')

    @pytest.mark.asyncio
    async def test_chain_cap_root_hardcap_blocks(self):
        """AC-08: Root quota=5, Root aggregate used=5 → blocker=(1, 'root_hardcap')."""
        from bisheng.role.domain.services.quota_service import QuotaService

        child = _make_tenant(5, parent_tenant_id=1, quota_config={'knowledge_space': 10})
        root = _make_tenant(1, parent_tenant_id=None, quota_config={'knowledge_space': 5})
        aget_map = {5: child, 1: root}

        with patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                   new=AsyncMock(side_effect=lambda tid: aget_map.get(tid))), \
             patch.object(QuotaService, '_count_usage_strict',
                          new=AsyncMock(return_value=3)), \
             patch.object(QuotaService, '_aggregate_root_usage',
                          new=AsyncMock(return_value=5)):
            effective, blocker = await QuotaService._apply_tenant_chain_cap(
                role_quota=-1, tenant_id=5, resource_type='knowledge_space',
            )

        assert effective == 0
        assert blocker == (1, 'root_hardcap')

    @pytest.mark.asyncio
    async def test_chain_cap_root_only_chain_for_root_user(self):
        """Root user: chain has only [Root]; no Child node check."""
        from bisheng.role.domain.services.quota_service import QuotaService

        root = _make_tenant(1, parent_tenant_id=None, quota_config={'workflow': 50})

        with patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                   new=AsyncMock(return_value=root)), \
             patch.object(QuotaService, '_aggregate_root_usage',
                          new=AsyncMock(return_value=20)):
            effective, blocker = await QuotaService._apply_tenant_chain_cap(
                role_quota=-1, tenant_id=1, resource_type='workflow',
            )

        assert effective == 30  # 50-20
        assert blocker is None

    @pytest.mark.asyncio
    async def test_chain_cap_takes_min_of_chain_and_role(self):
        """role_quota=8, Child remaining=10, Root remaining=20 → effective=min(8,10,20)=8."""
        from bisheng.role.domain.services.quota_service import QuotaService

        child = _make_tenant(5, parent_tenant_id=1, quota_config={'workflow': 30})
        root = _make_tenant(1, parent_tenant_id=None, quota_config={'workflow': 100})
        aget_map = {5: child, 1: root}

        with patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                   new=AsyncMock(side_effect=lambda tid: aget_map.get(tid))), \
             patch.object(QuotaService, '_count_usage_strict',
                          new=AsyncMock(return_value=20)), \
             patch.object(QuotaService, '_aggregate_root_usage',
                          new=AsyncMock(return_value=80)):
            effective, blocker = await QuotaService._apply_tenant_chain_cap(
                role_quota=8, tenant_id=5, resource_type='workflow',
            )

        # Child remaining=10, Root remaining=20, role=8 → min=8.
        assert effective == 8
        assert blocker is None


class TestCheckQuotaExceptions:
    """AC-01, AC-04, AC-08: exception class + Msg variant branches."""

    @pytest.mark.asyncio
    async def test_admin_user_bypasses_all_checks(self):
        """Admin → True without any DB call (INV-T5)."""
        from bisheng.role.domain.services.quota_service import QuotaService

        admin = _make_admin_user()
        # Force chain cap to raise if called; admin should short-circuit before.
        with patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(side_effect=AssertionError('should not be called'))):
            result = await QuotaService.check_quota(
                user_id=1, resource_type='knowledge_space', tenant_id=1, login_user=admin,
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_tenant_limit_raises_19401(self):
        """AC-01: leaf Child limit exceeded → TenantQuotaExceededError (19401)."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantQuotaExceededError

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(0, (5, 'tenant_limit')))):
            with pytest.raises(TenantQuotaExceededError) as exc:
                await QuotaService.check_quota(
                    user_id=10, resource_type='knowledge_space', tenant_id=5, login_user=user,
                )
        assert exc.value.Code == 19401
        assert '5' in str(exc.value)

    @pytest.mark.asyncio
    async def test_root_hardcap_msg_contains_group_exhausted(self):
        """AC-08: Root hardcap → Msg contains '集团总量已耗尽'."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantQuotaExceededError

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(0, (1, 'root_hardcap')))):
            with pytest.raises(TenantQuotaExceededError) as exc:
                await QuotaService.check_quota(
                    user_id=10, resource_type='knowledge_space', tenant_id=5, login_user=user,
                )
        assert exc.value.Code == 19401
        assert '集团总量已耗尽' in str(exc.value)

    @pytest.mark.asyncio
    async def test_storage_gb_raises_19403(self):
        """AC-04: storage_gb with any blocker → TenantStorageQuotaExceededError (19403)."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(0, (5, 'tenant_limit')))):
            with pytest.raises(TenantStorageQuotaExceededError) as exc:
                await QuotaService.check_quota(
                    user_id=10, resource_type='storage_gb', tenant_id=5, login_user=user,
                )
        assert exc.value.Code == 19403

    @pytest.mark.asyncio
    async def test_knowledge_space_file_raises_19403_not_19401(self):
        """AC-04 variant: knowledge_space_file also routes to storage errcode (19403)."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(0, (5, 'tenant_limit')))):
            with pytest.raises(TenantStorageQuotaExceededError) as exc:
                await QuotaService.check_quota(
                    user_id=10, resource_type='knowledge_space_file', tenant_id=5, login_user=user,
                )
        assert exc.value.Code == 19403

    @pytest.mark.asyncio
    async def test_role_quota_exhausted_raises_19402(self):
        """AC-01: chain passes but user_used >= effective → TenantRoleQuotaExceededError (19402)."""
        from bisheng.role.domain.services.quota_service import QuotaService
        from bisheng.common.errcode.tenant_quota import TenantRoleQuotaExceededError

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(5, None))), \
             patch.object(QuotaService, 'get_user_resource_count',
                          new=AsyncMock(return_value=5)):
            with pytest.raises(TenantRoleQuotaExceededError) as exc:
                await QuotaService.check_quota(
                    user_id=10, resource_type='channel', tenant_id=5, login_user=user,
                )
        assert exc.value.Code == 19402

    @pytest.mark.asyncio
    async def test_unlimited_effective_returns_true(self):
        """chain returns (-1, None) → True (no user_used check needed)."""
        from bisheng.role.domain.services.quota_service import QuotaService

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(-1, None))):
            result = await QuotaService.check_quota(
                user_id=10, resource_type='workflow', tenant_id=5, login_user=user,
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_happy_path_returns_true_under_effective(self):
        """chain passes + user_used < effective → True."""
        from bisheng.role.domain.services.quota_service import QuotaService

        user = _make_non_admin_user()
        with patch('bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
                   new=AsyncMock(return_value=[])), \
             patch.object(QuotaService, '_apply_tenant_chain_cap',
                          new=AsyncMock(return_value=(5, None))), \
             patch.object(QuotaService, 'get_user_resource_count',
                          new=AsyncMock(return_value=3)):
            result = await QuotaService.check_quota(
                user_id=10, resource_type='channel', tenant_id=5, login_user=user,
            )
        assert result is True
