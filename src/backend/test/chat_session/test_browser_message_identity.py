"""Native WS connections revalidate the person without resetting the chat worker."""

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.user.application import runtime_identity


@pytest.mark.parametrize("kind", ["assistant", "workflow"])
async def test_native_endpoint_supplies_a_guard_for_every_later_message(monkeypatch, kind):
    endpoint = importlib.import_module(f"bisheng.api.v1.{kind}")
    user = SimpleNamespace(user_id=849, user_name="migrated", tenant_id=1, token_version=0, is_global_super=False)
    facts = {"state": "active", "tenant_id": 1, "token_version": 0, "name": "migrated"}
    monkeypatch.setattr(runtime_identity, "read_current_person_facts", AsyncMock(return_value={849: facts}))
    monkeypatch.setattr(endpoint, "require_business_action", AsyncMock())
    captured = {}

    async def dispatch(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(endpoint.chat_manager, "dispatch_client", dispatch)
    socket = SimpleNamespace(state=SimpleNamespace(), close=AsyncMock())
    if kind == "assistant":
        await endpoint.chat(assistant_id="old-app", websocket=socket, login_user=user)
    else:

        @asynccontextmanager
        async def scope(*args, **kwargs):
            yield user

        monkeypatch.setattr(endpoint, "browser_workflow_scope", scope)
        await endpoint.workflow_ws(workflow_id="old-app", websocket=socket, login_user=user)
    admission = captured["message_admission"]
    async with admission() as execution:
        assert execution is None  # Preserve the native client's state and identity.
    facts["tenant_id"] = 60
    with pytest.raises(PermissionDeniedError):
        async with admission():
            pytest.fail("old connection was admitted after a move")


@pytest.mark.parametrize(
    "changed", [None, {"tenant_id": 60}, {"token_version": 1}, {"state": "inactive"}, {"state": "ambiguous"}]
)
async def test_native_message_refuses_a_changed_or_missing_person(monkeypatch, changed):
    user = SimpleNamespace(user_id=849, tenant_id=1, token_version=0, is_global_super=False)
    facts = {"state": "active", "tenant_id": 1, "token_version": 0}
    values = {} if changed is None else {849: {**facts, **changed}}
    monkeypatch.setattr(runtime_identity, "read_current_person_facts", AsyncMock(return_value=values))
    with pytest.raises(PermissionDeniedError):
        async with runtime_identity.browser_message_identity_scope(user):
            pytest.fail("changed identity was admitted")


@pytest.mark.parametrize("still_super", [True, False])
async def test_admin_home_is_distinct_from_the_selected_connection_view(monkeypatch, still_super):
    user = SimpleNamespace(user_id=849, tenant_id=1, token_version=4, is_global_super=True)
    monkeypatch.setattr(
        runtime_identity,
        "read_current_person_facts",
        AsyncMock(return_value={849: {"state": "active", "tenant_id": 1, "token_version": 4, "name": "admin"}}),
    )
    refresh = AsyncMock(return_value=SimpleNamespace(is_global_super=still_super))
    monkeypatch.setattr(runtime_identity.UserPayload, "init_login_user", refresh)
    with tenant_execution_scope(60):

        async def run():
            async with runtime_identity.browser_message_identity_scope(user) as execution:
                assert execution is None and get_current_tenant_id() == 60

        if still_super:
            await run()
        else:
            with pytest.raises(PermissionDeniedError):
                await run()
        assert get_current_tenant_id() == 60
    refresh.assert_awaited_once_with(
        user_id=849, user_name="admin", tenant_id=1, token_version=4, require_current_super=True
    )
