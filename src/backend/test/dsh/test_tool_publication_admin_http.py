"""AC-01, AC-02, AC-05: browser management contract and strict tenant inputs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from bisheng.common.errcode.dsh import DshToolPermissionDeniedError
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import tool_publications as admin
from bisheng.dsh.tool_runtime import get_tool_service


async def test_management_wraps_data_and_uses_verified_actor():
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    user = SimpleNamespace(user_id=9, tenant_id=2, is_global_super=False)
    item = {"tool_id": 7, "tool_code": "search", "enabled": True, "revision": 1}
    service = SimpleNamespace(
        list=AsyncMock(return_value={"data": [item], "total": 1}),
        get=AsyncMock(return_value=item),
        put=AsyncMock(return_value=item),
    )
    app.dependency_overrides[admin.admin_user] = lambda: user
    app.dependency_overrides[get_runtime] = lambda: object()
    app.dependency_overrides[get_tool_service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = "/api/v1/dsh/admin/tool-publications"
        response = await client.get(base + "?offset=0&limit=1")
        assert response.json()["status_code"] == 200 and response.json()["data"]["total"] == 1
        assert service.list.await_args.args == (user, 0, 1)
        response = await client.put(base + "/search", json={"tool_id": 7, "enabled": True})
        assert response.json()["data"] == item and service.put.await_args.args[0] is user
        assert (await client.get(base + "/search")).json()["data"] == item
        for path in (base + "?tenant_id=3", base + "/search?tenant_id=3"):
            rejected = await client.get(path)
            assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "tool_arguments_invalid"
        rejected = await client.put(base + "/search", json={"tool_id": 7, "enabled": True, "tenant_id": 3})
        assert rejected.status_code == 400
        rejected = await client.put(base + "/search", headers={"Content-Type": "application/json"}, content="x" * 16385)
        assert rejected.status_code == 413 and rejected.json()["error"]["code"] == "tool_input_too_large"

        async def denied():
            raise DshToolPermissionDeniedError()

        app.dependency_overrides[admin.admin_user] = denied
        rejected = await client.put(base + "/search", json={"tool_id": 7, "enabled": True})
        assert rejected.status_code == 403 and rejected.json()["error"]["code"] == "tool_permission_denied"
        assert service.put.await_count == 1
