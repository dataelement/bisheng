from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient


async def test_business_operation_waits_for_durable_audit_intent():
    from bisheng.open_api.application.kunlian_http import KunlianApiRoute, get_kunlian_request_user, kunlian_capability

    events = []

    class Access:
        @asynccontextmanager
        async def use_user(self, authorization, user_account, *, capability):
            assert (user_account, capability) == ("account-a", "write")
            yield SimpleNamespace(user=SimpleNamespace(user_id=17))

    class Audit:
        async def begin(self, access, method, route, target_id, trace_id):
            events.append("intent")
            return "audit-ref"

        async def finish(self, audit_id, status):
            events.append((audit_id, status))

    app = FastAPI()
    app.state.kunlian_access_service = Access()
    app.state.kunlian_request_limiter = AsyncMock(return_value=None)
    app.state.kunlian_audit_service = Audit()
    router = APIRouter(route_class=KunlianApiRoute)

    @router.post("/write")
    @kunlian_capability("write")
    async def write(access=Depends(get_kunlian_request_user)):
        events.append("business")
        return {"ok": True}

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/write", params={"user_account": "account-a"})
    assert response.status_code == 200
    assert events == ["intent", "business", ("audit-ref", 200)]
