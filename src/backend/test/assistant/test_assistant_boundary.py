"""Assistant configuration references and websocket rebinding are authorization boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import current_tenant_id, visible_tenant_ids


@pytest.fixture
def boundary(monkeypatch):
    from bisheng.assistant.domain.services import assistant_boundary_service as service

    kb = SimpleNamespace(id=11, type=0, tenant_id=1, user_id=22)
    assistant = SimpleNamespace(id="target", tenant_id=1, is_delete=False, status=2)
    repo = SimpleNamespace(
        knowledge=AsyncMock(return_value=[kb]),
        assistant=AsyncMock(return_value=assistant),
        session=AsyncMock(return_value=None),
    )
    permission = AsyncMock()
    monkeypatch.setattr(service, "AssistantBoundaryRepository", repo)
    monkeypatch.setattr(service, "require_business_action", permission)
    tid = current_tenant_id.set(1)
    visible = visible_tenant_ids.set(frozenset({1}))
    try:
        yield SimpleNamespace(
            service=service.AssistantBoundaryService,
            repo=repo,
            permission=permission,
            kb=kb,
            assistant=assistant,
            user=SimpleNamespace(user_id=7, tenant_id=1),
        )
    finally:
        visible_tenant_ids.reset(visible)
        current_tenant_id.reset(tid)


async def test_binding_requires_real_knowledge_use(boundary):
    h = boundary
    await h.service.authorize_knowledge_bindings(h.user, [11])
    h.permission.assert_awaited_once_with(h.user, resource_type="knowledge_library", resource_id=11, action="use")


async def test_space_binding_requires_actual_space_visible_action(boundary):
    h = boundary
    h.kb.type = 3
    await h.service.authorize_knowledge_bindings(h.user, [11])
    h.permission.assert_awaited_once_with(h.user, resource_type="knowledge_space", resource_id=11, action="visible")


@pytest.mark.parametrize("kind", ["missing", "foreign", "bad_type"])
async def test_invalid_binding_denied_before_permission_shortcuts(boundary, kind):
    h = boundary
    if kind == "missing":
        h.repo.knowledge.return_value = []
    elif kind == "foreign":
        h.kb.tenant_id = 8
    else:
        h.kb.type = 99
    with pytest.raises(HTTPException):
        await h.service.authorize_knowledge_bindings(h.user, [11])
    h.permission.assert_not_awaited()


async def test_binding_denied_by_current_use_action(boundary):
    h = boundary
    h.permission.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await h.service.authorize_knowledge_bindings(h.user, [11])


async def test_binding_validates_entire_batch_before_authorization(boundary):
    h = boundary
    with pytest.raises(HTTPException):
        await h.service.authorize_knowledge_bindings(h.user, [11, 999])
    h.permission.assert_not_awaited()


async def test_chat_target_requires_use_before_agent_or_history(boundary):
    h = boundary
    await h.service.authorize_chat_target(h.user, "target", "fresh", None, original_assistant_id="old")
    h.permission.assert_awaited_once_with(h.user, resource_type="assistant", resource_id="target", action="use")


@pytest.mark.parametrize("kind", ["foreign", "other_user", "wrong_app", "deleted", "api_subject"])
async def test_switch_refuses_invalid_existing_session(boundary, kind):
    h = boundary
    session = SimpleNamespace(tenant_id=1, user_id=7, flow_id="target", is_delete=False, api_subject_type=None)
    if kind == "foreign":
        session.tenant_id = 8
    elif kind == "other_user":
        session.user_id = 8
    elif kind == "wrong_app":
        session.flow_id = "other"
    elif kind == "deleted":
        session.is_delete = True
    else:
        session.api_subject_type = "public_v3"
    h.repo.session.return_value = session
    with pytest.raises(HTTPException):
        await h.service.authorize_chat_target(h.user, "target", "victim", None, original_assistant_id="old")


async def test_guest_cannot_rebind_to_different_app_even_super_operator(boundary):
    h = boundary
    subject = SimpleNamespace(subject_type="public_v3", tenant_id=1, resource_id="old", matches=lambda row: True)
    with pytest.raises(HTTPException):
        await h.service.authorize_chat_target(h.user, "target", "fresh", subject, original_assistant_id="old")
    h.permission.assert_not_awaited()


async def test_legitimate_owner_existing_session_allowed(boundary):
    h = boundary
    h.repo.session.return_value = SimpleNamespace(
        tenant_id=1, user_id=7, flow_id="target", is_delete=False, api_subject_type=None
    )
    await h.service.authorize_chat_target(h.user, "target", "own", None, original_assistant_id="target")


async def test_root_shared_binding_requires_explicit_current_action(boundary):
    h = boundary
    h.kb.tenant_id = 1
    h.kb.is_shared = True
    token = current_tenant_id.set(2)
    visible = visible_tenant_ids.set(frozenset({1, 2}))
    try:
        await h.service.authorize_knowledge_bindings(h.user, [11])
        h.permission.assert_awaited_once()
    finally:
        visible_tenant_ids.reset(visible)
        current_tenant_id.reset(token)


async def test_denied_binding_does_not_persist_any_assistant_or_link(monkeypatch):
    from bisheng.api.services import assistant as service
    from bisheng.api.v1.schemas import AssistantUpdateReq
    from bisheng.assistant.domain.services.assistant_boundary_service import AssistantBoundaryService

    assistant = SimpleNamespace(id="a", user_id=7, name="old", tenant_id=1)
    monkeypatch.setattr(service.AssistantDao, "get_one_assistant", Mock(return_value=assistant))
    monkeypatch.setattr(service.AssistantService, "check_update_permission_async", AsyncMock())
    monkeypatch.setattr(
        AssistantBoundaryService, "authorize_knowledge_bindings", AsyncMock(side_effect=UnAuthorizedError())
    )
    runtime = SimpleNamespace(aprepare_source_bindings=AsyncMock(), aapply_source_bindings=AsyncMock())
    monkeypatch.setattr(service, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
    update = AsyncMock()
    links = AsyncMock()
    monkeypatch.setattr(service.AssistantRepository, "asave", update)
    monkeypatch.setattr(service.AssistantRepository, "areplace_links", links)
    with pytest.raises(UnAuthorizedError):
        await service.AssistantService.update_assistant(
            None, SimpleNamespace(user_id=7), AssistantUpdateReq(id="a", knowledge_list=[11], name="new")
        )
    assert assistant.name == "old"
    update.assert_not_called()
    links.assert_not_awaited()
    runtime.aprepare_source_bindings.assert_not_awaited()
    runtime.aapply_source_bindings.assert_not_awaited()


async def test_cached_agent_revalidates_before_history_and_refreshes_tools(monkeypatch):
    from bisheng.api.services.assistant_agent import AssistantAgent
    from bisheng.common.chat.client import ChatClient

    client = object.__new__(ChatClient)
    client.login_user = SimpleNamespace(user_id=7)
    client.client_id, client.chat_id, client.session_subject = "target", "own", None
    client.gpts_agent = SimpleNamespace(refresh_knowledge_authorization=AsyncMock())
    client.gpts_async_callback = object()
    client.init_chat_history = AsyncMock()
    authorize = AsyncMock()
    monkeypatch.setattr(AssistantAgent, "authorize_chat_target", authorize)
    await client.init_gpts_agent()
    authorize.assert_awaited_once()
    client.gpts_agent.refresh_knowledge_authorization.assert_awaited_once_with(client.gpts_async_callback)
    client.init_chat_history.assert_not_awaited()
    authorize.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await client.init_gpts_agent()
    assert client.gpts_agent.refresh_knowledge_authorization.await_count == 1


async def test_denied_rebind_keeps_previous_client_state(monkeypatch):
    from bisheng.api.services.assistant_agent import AssistantAgent
    from bisheng.common.chat.client import ChatClient

    client = object.__new__(ChatClient)
    client.client_key = "c"
    client.client_id, client.chat_id = "old", "own"
    client.login_user = SimpleNamespace(user_id=7)
    client.websocket = SimpleNamespace(send_json=AsyncMock())
    client.finalizing_tasks = set()
    client.session_subject = None
    client.kwargs = {}
    client.gpts_agent, client.gpts_async_callback = object(), object()
    client.chat_history = ["old-history"]
    client.clear_stream_queue = AsyncMock()
    client.init_gpts_agent = AsyncMock()
    client.send_response = AsyncMock()
    before = (client.client_id, client.chat_id, client.gpts_agent, client.gpts_async_callback, client.chat_history[:])
    monkeypatch.setattr(AssistantAgent, "authorize_chat_target", AsyncMock(side_effect=UnAuthorizedError()))
    await client.handle_gpts_message({"inputs": {"data": {"id": "target", "chatId": "foreign"}}})
    assert (
        client.client_id,
        client.chat_id,
        client.gpts_agent,
        client.gpts_async_callback,
        client.chat_history,
    ) == before
    client.init_gpts_agent.assert_not_awaited()
