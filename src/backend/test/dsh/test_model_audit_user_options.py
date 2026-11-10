"""Audit user options share administrator tenant authorization."""

from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.tenant.domain.services.tenant_service import TenantService
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, fixture


async def test_user_options_reuse_exact_tenant_scope_and_return_minimal_fields(monkeypatch):
    async def directory(tenant_id, **kwargs):
        assert get_current_tenant_id() == tenant_id
        assert kwargs["page"] == 2 and kwargs["page_size"] == 10
        assert kwargs["keyword"] == "alice"
        return {"data": [{"user_id": 20, "user_name": "Alice", "avatar": "private"}], "total": 21}

    loader = AsyncMock(side_effect=directory)
    monkeypatch.setattr(TenantService, "aget_tenant_users", loader)
    async with fixture() as (_harness, client, _objects):
        for headers, tenant in ((LOCAL_ADMIN, None), (LOCAL_ADMIN, 2), (ADMIN, 3)):
            params = {"page": 2, "page_size": 10, "keyword": "alice"}
            if tenant is not None:
                params["tenant_id"] = tenant
            response = await client.get(BASE + "/users", headers=headers, params=params)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["data"] == {"data": [{"user_id": 20, "user_name": "Alice"}], "total": 21}
        assert [call.args[0] for call in loader.await_args_list] == [2, 2, 3]


async def test_user_options_reject_non_admin_and_cross_tenant_before_directory_access(monkeypatch):
    loader = AsyncMock()
    monkeypatch.setattr(TenantService, "aget_tenant_users", loader)
    async with fixture() as (_harness, client, _objects):
        assert (await client.get(BASE + "/users", headers=USER)).status_code == 403
        response = await client.get(BASE + "/users", headers=LOCAL_ADMIN, params={"tenant_id": 3})
        assert response.status_code == 403
        loader.assert_not_awaited()


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"keyword": "x" * 129}])
async def test_user_options_bound_pagination_and_search(params):
    async with fixture() as (_harness, client, _objects):
        assert (await client.get(BASE + "/users", headers=ADMIN, params=params)).status_code == 422
