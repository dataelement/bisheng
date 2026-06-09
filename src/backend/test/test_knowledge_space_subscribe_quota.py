"""Unit tests for the knowledge_space_subscribe role quota dimension.

Covers the F005 quota wiring added for "join knowledge space" limits:
default 100, multi-role max, admin unlimited, and that the resource is
registered as a countable dimension (SQL template + qualified column).
"""

from unittest.mock import AsyncMock, MagicMock, patch


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


def _make_user(user_id=10, tenant_id=1, is_admin=False):
    user = MagicMock()
    user.user_id = user_id
    user.tenant_id = tenant_id
    user.is_admin.return_value = is_admin
    return user


def test_default_quota_is_100():
    from bisheng.role.domain.services.quota_service import (
        DEFAULT_ROLE_QUOTA,
        QuotaResourceType,
    )

    assert QuotaResourceType.KNOWLEDGE_SPACE_SUBSCRIBE == "knowledge_space_subscribe"
    assert DEFAULT_ROLE_QUOTA["knowledge_space_subscribe"] == 100


def test_resource_is_countable_dimension():
    """Template must be registered (scoped to SPACE) so /me/quotas usage != silent 0."""
    from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES

    sql = _RESOURCE_COUNT_TEMPLATES["knowledge_space_subscribe"]
    assert "business_type='SPACE'" in sql
    assert "space_channel_member" in sql
    assert "{qualified_col}" in sql


async def test_no_roles_falls_back_to_default_100():
    from bisheng.role.domain.services.quota_service import (
        QuotaResourceType,
        QuotaService,
    )

    user = _make_user()
    tenant = _make_tenant(quota_config=None)  # tenant unlimited
    with (
        patch("bisheng.role.domain.services.quota_service.UserRoleDao") as mock_ur_dao,
        patch("bisheng.role.domain.services.quota_service.TenantDao") as mock_tenant_dao,
    ):
        mock_ur_dao.aget_user_roles = AsyncMock(return_value=[])
        mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

        result = await QuotaService.get_effective_quota(
            user_id=10,
            resource_type=QuotaResourceType.KNOWLEDGE_SPACE_SUBSCRIBE,
            tenant_id=1,
            login_user=user,
        )
    assert result == 100


async def test_multi_role_takes_max():
    from bisheng.role.domain.services.quota_service import (
        QuotaResourceType,
        QuotaService,
    )

    user = _make_user()
    user_roles = [_make_user_role(3), _make_user_role(4)]
    roles = [
        _make_role(3, {"knowledge_space_subscribe": 80}),
        _make_role(4, {"knowledge_space_subscribe": 150}),
    ]
    tenant = _make_tenant(quota_config=None)
    with (
        patch("bisheng.role.domain.services.quota_service.UserRoleDao") as mock_ur_dao,
        patch("bisheng.role.domain.services.quota_service.RoleDao") as mock_role_dao,
        patch("bisheng.role.domain.services.quota_service.TenantDao") as mock_tenant_dao,
    ):
        mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
        mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)
        mock_tenant_dao.aget_by_id = AsyncMock(return_value=tenant)

        result = await QuotaService.get_effective_quota(
            user_id=10,
            resource_type=QuotaResourceType.KNOWLEDGE_SPACE_SUBSCRIBE,
            tenant_id=1,
            login_user=user,
        )
    assert result == 150


async def test_admin_is_unlimited():
    from bisheng.role.domain.services.quota_service import (
        QuotaResourceType,
        QuotaService,
    )

    admin = _make_user(user_id=1, is_admin=True)
    result = await QuotaService.get_effective_quota(
        user_id=1,
        resource_type=QuotaResourceType.KNOWLEDGE_SPACE_SUBSCRIBE,
        tenant_id=1,
        login_user=admin,
    )
    assert result == -1


async def test_role_unlimited_returns_unlimited():
    from bisheng.role.domain.services.quota_service import (
        QuotaResourceType,
        QuotaService,
    )

    user = _make_user()
    user_roles = [_make_user_role(3)]
    roles = [_make_role(3, {"knowledge_space_subscribe": -1})]
    with (
        patch("bisheng.role.domain.services.quota_service.UserRoleDao") as mock_ur_dao,
        patch("bisheng.role.domain.services.quota_service.RoleDao") as mock_role_dao,
    ):
        mock_ur_dao.aget_user_roles = AsyncMock(return_value=user_roles)
        mock_role_dao.aget_role_by_ids = AsyncMock(return_value=roles)

        result = await QuotaService.get_effective_quota(
            user_id=10,
            resource_type=QuotaResourceType.KNOWLEDGE_SPACE_SUBSCRIBE,
            tenant_id=1,
            login_user=user,
        )
    assert result == -1
