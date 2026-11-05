"""The client must identify the authenticated tenant, not only the user's leaf."""

from types import SimpleNamespace
from unittest.mock import AsyncMock


async def test_user_info_exposes_authenticated_tenant(monkeypatch):
    import bisheng.utils.http_middleware as middleware
    from bisheng.database.models.tenant import TenantDao, UserTenantDao
    from bisheng.user.api import user as endpoint

    user = SimpleNamespace(
        user_id=9,
        tenant_id=42,
        is_admin=lambda: True,
        get_roles_web_menu=AsyncMock(return_value=("admin", [])),
        compute_menu_approval_modes=AsyncMock(return_value=(False, False)),
    )
    monkeypatch.setattr(endpoint.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_id=9)))
    monkeypatch.setattr(endpoint.UserRoleDao, "aget_user_roles", AsyncMock(return_value=[]))
    monkeypatch.setattr(endpoint.UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(endpoint.DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(endpoint.LoginUser, "user_entry_payload_for_read", AsyncMock(return_value={}))
    monkeypatch.setattr(middleware, "_check_is_global_super", AsyncMock(return_value=True))
    monkeypatch.setattr(UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=SimpleNamespace(tenant_id=1)))
    monkeypatch.setattr(TenantDao, "aget_by_id", AsyncMock(return_value=SimpleNamespace(tenant_name="root")))

    async def read(_user, **fields):
        return fields

    monkeypatch.setattr(endpoint.UserService, "build_user_read", read)
    response = await endpoint.get_info(user)
    assert response.data["tenant_id"] == 42
    assert response.data["leaf_tenant_id"] == 1
