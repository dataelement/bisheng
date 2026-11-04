"""T067/T069 覆盖 AC-01, AC-13, AC-14。来源只取已认证服务端主体。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.parametrize("source", [None, "kunlian"])
async def test_current_user_source_is_serialized_from_verified_principal_only(monkeypatch, source):
    from bisheng.database.models.tenant import TenantDao, UserTenantDao
    from bisheng.user.api import user as module
    from bisheng.user.domain.models.user import UserRead
    from bisheng.utils import http_middleware

    user = SimpleNamespace(
        user_id=17,
        auth_source=source,
        get_roles_web_menu=AsyncMock(return_value=("user", ["build"])),
        compute_menu_approval_modes=AsyncMock(return_value=(False, False)),
        is_admin=lambda: False,
    )
    for owner, name, result in (
        (module.UserDao, "aget_user", SimpleNamespace(user_id=17)),
        (module.UserRoleDao, "aget_user_roles", []),
        (module.UserGroupDao, "aget_user_admin_group", []),
        (module.DepartmentDao, "aget_user_admin_departments", []),
        (UserTenantDao, "aget_active_user_tenant", None),
        (TenantDao, "aget_by_id", SimpleNamespace(tenant_name="fixture")),
        (http_middleware, "_check_is_global_super", False),
        (module.LoginUser, "user_entry_payload_for_read", {}),
        (module.UserService, "build_user_read", UserRead.model_construct(user_id=17, user_name="fixture")),
    ):
        monkeypatch.setattr(owner, name, AsyncMock(return_value=result))
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1")
    app.dependency_overrides[module.LoginUser.get_login_user] = lambda: user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://fixture.invalid") as client:
        result = await client.get("/api/v1/user/info?auth_source=kunlian", headers={"X-Auth-Source": "kunlian"})
    assert result.status_code == 200
    data = result.json()["data"]
    assert data.get("auth_source") == source
    if source is None:
        assert "auth_source" not in data
