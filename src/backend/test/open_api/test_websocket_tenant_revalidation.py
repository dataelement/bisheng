"""F113: each new message has independent admission and a frozen worker identity."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.chat.client import ChatClient, ChatMessageExecution
from bisheng.common.chat.manager import ChatManager
from bisheng.common.chat.types import WorkType
from bisheng.common.errcode.open_api import ServiceAccountOwnerTenantMismatchError


@pytest.mark.parametrize("denied", [False, True])
async def test_message_admission_precedes_permissions_and_dispatch(denied):
    manager = ChatManager()
    manager._has_use_action = AsyncMock(return_value=True)
    client = SimpleNamespace(handle_message=AsyncMock())
    old = SimpleNamespace(user_id=21)
    current = SimpleNamespace(user_id=22)
    execution = ChatMessageExecution(operator=current, execution_snapshot={"tenant_id": 1})

    @asynccontextmanager
    async def admission():
        if denied:
            raise ServiceAccountOwnerTenantMismatchError()
        yield execution

    call = manager._dispatch_message(
        client,
        {"message": "next"},
        login_user=old,
        work_type=WorkType.GPTS,
        client_id="app",
        message_admission=admission,
    )
    if denied:
        with pytest.raises(ServiceAccountOwnerTenantMismatchError):
            await call
        manager._has_use_action.assert_not_awaited()
        client.handle_message.assert_not_awaited()
    else:
        assert await call is True
        manager._has_use_action.assert_awaited_once_with(current, WorkType.GPTS, "app")
        client.handle_message.assert_awaited_once_with({"message": "next"}, execution_context=execution)


async def test_existing_web_path_does_not_gain_a_new_admission_contract():
    manager = ChatManager()
    manager._has_use_action = AsyncMock(return_value=True)
    client = SimpleNamespace(handle_message=AsyncMock())
    original = SimpleNamespace(user_id=21)
    assert await manager._dispatch_message(client, {}, login_user=original, work_type=WorkType.GPTS, client_id="app")
    client.handle_message.assert_awaited_once_with({})


async def test_queued_messages_do_not_overwrite_each_others_identity(monkeypatch):
    from bisheng.common.chat import client as module

    queued = []
    monkeypatch.setattr(module.thread_pool, "submit", lambda *args, **kwargs: queued.append((args, kwargs)))
    original = ChatClient.__new__(ChatClient)
    original.login_user = SimpleNamespace(user_id=21)
    original.user_id = 21
    original.client_key = "f113"
    original.work_type = WorkType.GPTS
    original.kwargs = {}
    original.gpts_agent = object()
    original.gpts_async_callback = object()
    original.db_assistant = object()
    for owner in (22, 23):
        context = ChatMessageExecution(
            operator=SimpleNamespace(user_id=owner),
            execution_snapshot={"tenant_id": 1, "resource_owner_user_id": owner},
        )
        await original.handle_message({"owner": owner}, execution_context=context)
        with pytest.raises(TypeError):
            context.execution_snapshot["tenant_id"] = 9
    workers = [args[1].__self__ for args, _kwargs in queued]
    assert [worker.user_id for worker in workers] == [22, 23]
    assert [worker.login_user.user_id for worker in workers] == [22, 23]
    assert original.user_id == 21 and original.login_user.user_id == 21
    assert all(worker.gpts_agent is None and worker.gpts_async_callback is None for worker in workers)
    assert [worker.kwargs["execution_snapshot"]["resource_owner_user_id"] for worker in workers] == [22, 23]


async def test_v2_endpoint_supplies_fresh_admission_without_changing_session_partition(monkeypatch):
    from bisheng.open_api.domain.context import (
        get_current_open_api_principal,
        reset_current_open_api_principal,
        set_current_open_api_principal,
    )
    from bisheng.open_endpoints.api.endpoints import assistant as endpoint
    from test.open_api.test_websocket_auth import _principal, _websocket

    original = _principal()
    updated = original.model_copy(update={"resource_owner_user_id": 8})
    seen = []

    async def validate(_header):
        return updated

    @asynccontextmanager
    async def watcher(_socket):
        yield

    async def dispatch(*args, **kwargs):
        initial_subject = kwargs["session_subject"]
        async with kwargs["message_admission"]() as execution:
            assert execution.operator.user_id == 8
            assert execution.session_subject.subject_id == initial_subject.subject_id == original.actor_id
            assert execution.session_subject.compatibility_user_id == 8
            assert initial_subject.compatibility_user_id == 7
            assert execution.execution_snapshot["resource_owner_user_id"] == 8
            seen.append(execution)
        assert get_current_open_api_principal() is original

    monkeypatch.setattr(endpoint, "validate_bearer", validate)
    monkeypatch.setattr(endpoint, "watch_websocket_credential", watcher)
    monkeypatch.setattr(endpoint.PublishedAssistantService, "validate_websocket_session", AsyncMock())
    monkeypatch.setattr(endpoint.chat_manager, "dispatch_client", dispatch)
    monkeypatch.setattr(
        endpoint,
        "get_open_api_operator",
        lambda: SimpleNamespace(
            user_id=get_current_open_api_principal().resource_owner_user_id,
        ),
    )
    token = set_current_open_api_principal(original)
    try:
        await endpoint.chat(websocket=_websocket([(b"authorization", b"Bearer f113")]), assistant_id="f113")
    finally:
        reset_current_open_api_principal(token)
    assert len(seen) == 1
