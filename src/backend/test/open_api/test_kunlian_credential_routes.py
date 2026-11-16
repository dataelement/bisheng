"""凭据控制面不能让请求体声明自己是超管。"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_control_plane_registers_local_admin_dependency():
    name = "bisheng.open_api.api.endpoints.kunlian_credentials"
    assert importlib.util.find_spec(name) is not None, "F133 key control plane missing"
    module = importlib.import_module(name)
    assert len(module.router.routes) == 6
    for route in module.router.routes:
        dependencies = [dep.call for dep in route.dependant.dependencies]
        assert module.get_kunlian_key_admin in dependencies
        assert route.path.startswith("/identity-integrations/kunlian/api-keys")


@pytest.mark.parametrize("authorized", [False, True])
async def test_key_admin_uses_current_owner_facts_not_cached_super(authorized, monkeypatch):
    from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.user.application import external_identity
    from bisheng.utils import http_middleware

    module = importlib.import_module("bisheng.open_api.api.endpoints.kunlian_credentials")
    cached = AsyncMock(return_value=True)
    monkeypatch.setattr(http_middleware, "_check_is_global_super", cached)
    reads = []

    async def current_roles(self, user_id):
        reads.append((user_id, get_current_tenant_id()))
        return ()

    async def current_super(user_id, role_ids):
        assert (user_id, role_ids) == (42, ())
        assert get_current_tenant_id() == 1
        return authorized

    monkeypatch.setattr(
        external_identity.UserExternalIdentityProjectionRepository, "read_control_plane_actor_roles", current_roles
    )
    monkeypatch.setattr(external_identity, "check_current_global_super", current_super)
    user = SimpleNamespace(user_id=42, is_global_super=True)
    with tenant_execution_scope(99):
        if authorized:
            assert await module.get_kunlian_key_admin(user) is user
        else:
            with pytest.raises(KunlianIdentityUnavailableError):
                await module.get_kunlian_key_admin(user)
        assert get_current_tenant_id() == 99
    assert reads == [(42, 1)]
    cached.assert_not_awaited()
