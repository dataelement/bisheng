"""F113: tool admission must not reuse the transport's ownership snapshot."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import types
from sqlmodel import select

from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.application.service_account_tenancy import revalidate_service_account
from bisheng.open_api.domain.context import (
    get_current_open_api_principal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.open_mcp import server
from bisheng.open_mcp.auth import current_mcp_scope
from bisheng.open_mcp.contracts import ResourceListData
from test.open_api.test_service_account_tenancy import principal, seed


@pytest.mark.parametrize("moved", [False, True])
async def test_tool_uses_fresh_binding_and_preserves_shared_transport_scope(open_api_db, monkeypatch, moved):
    # The handler is under test, not the SDK transport constructor.
    monkeypatch.setattr(server, "StreamableHTTPSessionManager", lambda **kw: SimpleNamespace(app=kw["app"]))
    account = await seed(open_api_db)
    original = principal(account)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer f113")], "open_api_principal": original}
    calls = []

    async def validate(header):
        assert header == "Bearer f113"
        calls.append(header)
        return await revalidate_service_account(original)

    async def execute(name, arguments):
        assert get_current_open_api_principal().authorization_subject_type == "service_account"
        return ResourceListData(data=[], page_size=10, has_more=False)

    executor = AsyncMock(side_effect=execute)
    monkeypatch.setattr(server, "execute_tool", executor)
    monkeypatch.setattr(server.open_api_call_audit_service, "enqueue", lambda _event: None)
    monkeypatch.setattr(server, "validate_bearer", validate, raising=False)
    if moved:
        async with open_api_db() as session:
            member = (await session.exec(select(UserTenant))).one()
            member.tenant_id = 2
            session.add(member)
            await session.commit()
    token = set_current_open_api_principal(original)
    scope_token = current_mcp_scope.set(scope)
    try:
        runtime = server.create_open_mcp_runtime()
        result = await runtime.manager.app.request_handlers[types.CallToolRequest](
            types.CallToolRequest(
                params=types.CallToolRequestParams(name="bisheng_knowledge_list", arguments={"type": 0})
            )
        )
        assert result.root.isError is moved
        assert executor.await_count == (0 if moved else 1)
        assert len(calls) == 1
        assert get_current_open_api_principal() is original
        assert scope["open_api_principal"] is original
    finally:
        current_mcp_scope.reset(scope_token)
        reset_current_open_api_principal(token)
