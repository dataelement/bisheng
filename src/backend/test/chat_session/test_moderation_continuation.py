"""Real normal writers after the legacy Gateway creates a Home-owned session."""

from types import SimpleNamespace

import pytest
from sqlmodel import select

from test.chat_session.test_legacy_moderation_callbacks import setup as _setup_fixture

setup = _setup_fixture


def intercept(setup, resource="flow-b"):
    from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService

    return ChatMessageService.add_qa_messages(
        SimpleNamespace(
            chat_id="continued", flow_id=resource, human_message='{"input":"blocked"}', answer_message="blocked"
        ),
        setup.user,
        "127.0.0.1",
    )


@pytest.fixture
def continued(setup, monkeypatch):
    from bisheng.chat_session.domain.repositories import moderation_repository

    monkeypatch.setattr(moderation_repository, "stamp_session", lambda row: None)
    return setup


def rows(setup):
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter(), setup.db() as db:
        session = db.get(setup.sessions, "continued")
        messages = db.exec(select(setup.messages).where(setup.messages.chat_id == "continued")).all()
        return session, messages


@pytest.mark.parametrize("home,super_user", [(1, True), (60, False)])
def test_workflow_continues_home_session_without_duplicate_or_mixed_tenant(continued, monkeypatch, home, super_user):
    from bisheng.api.v1.schemas import ChatResponse
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.worker.workflow.redis_callback import RedisCallback

    continued.user.tenant_id, continued.user.is_global_super = home, super_user
    intercept(continued)
    callback = RedisCallback.__new__(RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id = "continued", "flow-b", 7
    callback.source, callback.create_session, callback.new_session = "platform", False, None
    callback._finalize_citation_items = lambda *args, **kwargs: []
    with tenant_execution_scope(60):
        callback.save_chat_message(ChatResponse(type="end", category="answer", message="normal answer"))
        assert get_current_tenant_id() == 60
    session, messages = rows(continued)
    assert session.tenant_id == home
    assert len(messages) == 3 and {row.tenant_id for row in messages} == {home}


@pytest.mark.parametrize("home,super_user", [(1, True), (60, False)])
async def test_assistant_continues_home_session_without_duplicate_or_mixed_tenant(
    continued, monkeypatch, home, super_user
):
    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.common.chat.client import ChatClient
    from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, tenant_execution_scope

    # Seed an assistant with a different owner tenant, without changing existing data.
    from bisheng.database.models.assistant import Assistant

    with bypass_tenant_filter(), continued.db() as db:
        db.add(Assistant(id="assistant-b", name="B", tenant_id=60, user_id=8))
        db.commit()
    # First interception uses a synchronous owner; run outside the active loop.
    import anyio

    continued.user.tenant_id, continued.user.is_global_super = home, super_user
    await anyio.to_thread.run_sync(intercept, continued, "assistant-b")
    client = ChatClient.__new__(ChatClient)
    client.chat_id, client.client_id, client.user_id = "continued", "assistant-b", 7
    client.login_user = continued.user
    client.client_key, client.chat_history, client.new_session = "connection", [], None
    client.db_assistant, client.session_subject = SimpleNamespace(name="B"), None
    client.kwargs = {"conversation_persistence": ConversationPersistence(7, user=continued.user)}
    with tenant_execution_scope(60):
        saved = await client.add_message("human", "normal question", "question")
        await client.add_message("bot", "normal answer", "answer")
        assert get_current_tenant_id() == 60 and saved.tenant_id == home
    session, messages = rows(continued)
    assert session.tenant_id == home
    assert len(messages) == 4 and {row.tenant_id for row in messages} == {home}


def assistant_client(setup, resource="flow-b"):
    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.common.chat.client import ChatClient

    client = ChatClient.__new__(ChatClient)
    client.chat_id, client.client_id, client.user_id = "continued", resource, 7
    client.login_user, client.session_subject = setup.user, None
    client.client_key, client.chat_history, client.new_session = "connection", [], None
    client.db_assistant = SimpleNamespace(name="B")
    client.latest_history_num = 10
    client.kwargs = {"conversation_persistence": ConversationPersistence(7, user=setup.user)}
    return client


async def test_assistant_reconnect_loads_original_history_and_keeps_execution_scope(continued):
    import anyio

    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope

    await anyio.to_thread.run_sync(intercept, continued)
    client = assistant_client(continued)
    with tenant_execution_scope(60):
        await client.init_chat_history()
        assert len(client.chat_history) == 2
        assert get_current_tenant_id() == 60
        await client.add_message("human", "after reconnect", "question")
        assert get_current_tenant_id() == 60
    assert {m.tenant_id for m in rows(continued)[1]} == {1}


@pytest.mark.parametrize(
    "violation", ["ordinary", "credential", "wrong_resource", "wrong_target", "foreign_owner", "mixed_history"]
)
def test_continuation_rejects_foreign_or_inconsistent_subject(continued, violation):
    from fastapi import HTTPException

    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, tenant_execution_scope

    intercept(continued)
    resource, execution = "flow-b", 60
    if violation == "ordinary":
        continued.user.is_global_super = False
    elif violation == "credential":
        continued.user._dsh_web_session_tenant_id = 60
    elif violation == "wrong_resource":
        resource = "shared-root"
    elif violation == "wrong_target":
        execution = 65
    elif violation == "foreign_owner":
        continued.user.user_id = 8
    elif violation == "mixed_history":
        with bypass_tenant_filter(), continued.db() as db:
            db.add(
                continued.messages(
                    chat_id="continued",
                    flow_id="flow-b",
                    user_id=7,
                    tenant_id=60,
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="old mismatch",
                )
            )
            db.commit()
    before = [(m.id, m.tenant_id, m.message) for m in rows(continued)[1]]
    port = ConversationPersistence(continued.user.user_id, user=continued.user)
    with tenant_execution_scope(execution):
        with pytest.raises(HTTPException):
            with port.scope("continued", resource, continued.user.user_id):
                pytest.fail("invalid continuation must not reach persistence")
        assert get_current_tenant_id() == execution
    assert [(m.id, m.tenant_id, m.message) for m in rows(continued)[1]] == before


def test_atomic_writer_does_not_leave_message_when_new_session_conflicts(continued):
    from fastapi import HTTPException

    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.core.context.tenant import tenant_execution_scope

    intercept(continued)
    # Simulate a competing tenant creating the same ID after an earlier empty lookup.
    with tenant_execution_scope(60), pytest.raises(HTTPException):
        ConversationPersistence(7).save(
            continued.messages(
                chat_id="continued",
                flow_id="flow-b",
                user_id=7,
                is_bot=True,
                type="bot",
                category="answer",
                message="must roll back",
            ),
            continued.sessions(chat_id="continued", flow_id="flow-b", user_id=7, flow_type=10),
        )
    assert len(rows(continued)[1]) == 2
    assert {m.tenant_id for m in rows(continued)[1]} == {1}


def test_no_gateway_new_conversation_stays_in_execution_tenant(continued):
    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope

    port = ConversationPersistence(7, user=continued.user)
    with tenant_execution_scope(60):
        with port.scope("continued", "flow-b", 7):
            port.save(
                continued.messages(
                    chat_id="continued",
                    flow_id="flow-b",
                    user_id=7,
                    is_bot=True,
                    type="bot",
                    category="answer",
                    message="normal",
                ),
                continued.sessions(chat_id="continued", flow_id="flow-b", user_id=7, flow_type=10),
            )
        assert get_current_tenant_id() == 60
    assert rows(continued)[0].tenant_id == 60


async def test_refreshed_browser_reads_owned_home_history_under_managed_target(continued, monkeypatch, tmp_path):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    import anyio
    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.admin.application import request_admission
    from bisheng.chat_session.domain import chat
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.database.models import message, session
    from bisheng.main import app as production

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'moderation.db'}")

    @asynccontextmanager
    async def database():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(message, "get_async_db_session", database)
    monkeypatch.setattr(session, "get_async_db_session", database)
    monkeypatch.setattr(chat.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_name="tester")))
    monkeypatch.setattr(chat.WorkFlowService, "get_logo_share_link", lambda logo: logo)
    monkeypatch.setattr(
        request_admission, "request_target", AsyncMock(return_value=SimpleNamespace(tenant_id=60, source="selected"))
    )
    for route in production.routes:
        if route.path in {"/api/v1/chat/history", "/api/v1/chat/info"}:
            continued.app.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    from bisheng.chat_session.api.endpoints.chat import header_share_token_parser

    continued.app.dependency_overrides[header_share_token_parser] = lambda: None
    request_admission.install_request_admission(continued.app)
    await anyio.to_thread.run_sync(intercept, continued)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(continued.app), base_url="http://test") as client:
            with tenant_execution_scope(60):
                response = await client.get(
                    "/api/v1/chat/history",
                    params={"chat_id": "continued", "flow_id": "flow-b"},
                    headers={"X-Management-Tenant": "60"},
                )
                assert response.json()["status_code"] == 200
                assert len(response.json()["data"]) == 2
                assert response.headers["X-Management-Tenant"] == "60"
                info = await client.get(
                    "/api/v1/chat/info", params={"chat_id": "continued"}, headers={"X-Management-Tenant": "60"}
                )
                assert info.json()["data"]["tenant_id"] == 1
                assert get_current_tenant_id() == 60
    finally:
        await engine.dispose()


def test_browser_endpoints_inject_persistence_port_without_gateway_dependency():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "bisheng/api/v1"
    for name in ("assistant.py", "workflow.py"):
        tree = ast.parse((root / name).read_text())
        dispatches = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "dispatch_client"
        ]
        assert len(dispatches) == 1
        assert any(k.arg == "conversation_persistence" for k in dispatches[0].keywords)


async def test_assistant_generation_stays_in_resource_tenant_while_messages_use_home(continued, monkeypatch):
    import asyncio
    from queue import Queue
    from unittest.mock import AsyncMock, Mock

    import anyio
    from langchain_core.messages import AIMessage

    from bisheng.common.chat.clients import base
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope

    await anyio.to_thread.run_sync(intercept, continued)
    client = assistant_client(continued)
    client.finalizing_tasks, client.background_tasks = set(), set()
    client.stream_queue, client.gpts_async_callback = Queue(), None
    client.send_response = AsyncMock()
    client.init_gpts_agent = AsyncMock()
    client.generate_session_title = AsyncMock()
    monkeypatch.setattr(base, "ensure_client_execution_lease", AsyncMock(return_value="accepted"))

    async def generate(question, history, callback):
        assert get_current_tenant_id() == 60
        assert question == "valid input"
        return [*history, AIMessage(content="normal result")]

    client.gpts_agent = SimpleNamespace(
        run=AsyncMock(side_effect=generate),
        llm=SimpleNamespace(streaming=False),
        reset_citation_registry_items=Mock(),
        collect_citation_registry_items=lambda: [],
    )
    with tenant_execution_scope(60):
        await client.init_chat_history()
        await client.handle_gpts_message({"inputs": {"input": "valid input"}})
        if client.background_tasks:
            await asyncio.gather(*client.background_tasks)
        assert get_current_tenant_id() == 60
    client.gpts_agent.run.assert_awaited_once()
    assert any(m.message == "normal result" for m in rows(continued)[1])
    assert {m.tenant_id for m in rows(continued)[1]} == {1}
    assert not any(call.args and call.args[0] == "system" for call in client.send_response.call_args_list)


async def test_workflow_reconnect_reads_home_session_history(continued, monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    import anyio
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.common.chat.clients.workflow_client import WorkflowClient
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.database.models import message

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'moderation.db'}")

    @asynccontextmanager
    async def database():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(message, "get_async_db_session", database)
    await anyio.to_thread.run_sync(intercept, continued)
    client = WorkflowClient.__new__(WorkflowClient)
    client.chat_id, client.client_id, client.user_id = "continued", "flow-b", 7
    client.latest_history = None
    client.kwargs = {"conversation_persistence": ConversationPersistence(7, user=continued.user)}
    try:
        with tenant_execution_scope(60):
            await client.init_history()
            assert client.latest_history.tenant_id == 1
            assert get_current_tenant_id() == 60
    finally:
        await engine.dispose()


def test_workflow_input_update_uses_original_conversation_tenant(continued):
    import json
    from unittest.mock import Mock

    from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, tenant_execution_scope
    from bisheng.worker.workflow.redis_callback import RedisCallback

    intercept(continued)
    with bypass_tenant_filter(), continued.db() as db:
        prompt = continued.messages(
            chat_id="continued",
            flow_id="flow-b",
            user_id=7,
            tenant_id=1,
            is_bot=True,
            type="end",
            category="output_with_input_msg",
            message=json.dumps({"node_id": "node", "key": "question"}),
        )
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        prompt_id = prompt.id
    callback = RedisCallback.__new__(RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id, callback.source = "continued", "flow-b", 7, "platform"
    callback.redis_client, callback.workflow_input_key, callback.workflow_expire_time = Mock(), "test-input", 30
    with tenant_execution_scope(60):
        callback.set_user_input({"node": {"question": "new input"}}, prompt_id, "", verify_input=True)
        assert get_current_tenant_id() == 60
    saved = next(m for m in rows(continued)[1] if m.id == prompt_id)
    assert json.loads(saved.message)["hisValue"] == "new input" and saved.tenant_id == 1
    callback.redis_client.set.assert_called_once()


def test_workflow_title_reads_storage_owner_but_uses_execution_models(continued, monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.worker.workflow import redis_callback as module

    intercept(continued)
    callback = module.RedisCallback.__new__(module.RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id = "continued", "flow-b", 7
    callback.tenant_id, callback.source, callback.new_session = 60, "platform", None

    def config(*, tenant_id):
        assert tenant_id == 60 and get_current_tenant_id() == 60
        return SimpleNamespace(chat_title_llm=SimpleNamespace(id="title-model"))

    def llm(**kwargs):
        assert get_current_tenant_id() == 60
        return object()

    monkeypatch.setattr(module.LLMService, "get_workbench_llm_sync", config)
    monkeypatch.setattr(module.LLMService, "get_bisheng_llm_sync", llm)
    monkeypatch.setattr(module, "generate_conversation_title_sync", lambda **kwargs: "continued title")
    with tenant_execution_scope(60):
        callback.generate_session_title()
        assert get_current_tenant_id() == 60
    assert rows(continued)[0].name == "continued title"


def test_failed_message_insert_rolls_back_new_session(continued):
    from sqlalchemy.exc import IntegrityError

    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.core.context.tenant import tenant_execution_scope

    with tenant_execution_scope(60), pytest.raises(IntegrityError):
        ConversationPersistence(7).save(
            continued.messages(
                chat_id="continued",
                flow_id="flow-b",
                user_id=7,
                is_bot=True,
                category="answer",
                message="missing required type",
            ),
            continued.sessions(chat_id="continued", flow_id="flow-b", user_id=7, flow_type=10),
        )
    session, messages = rows(continued)
    assert session is None and messages == []


def test_platform_input_cannot_update_another_conversations_message(continued):
    import json
    from unittest.mock import Mock

    from bisheng.common.errcode.flow import WorkFlowInvalidUserInputError
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.worker.workflow.redis_callback import RedisCallback

    intercept(continued)
    callback = RedisCallback.__new__(RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id, callback.source = "continued", "flow-b", 7, "platform"
    callback.redis_client, callback.workflow_input_key, callback.workflow_expire_time = Mock(), "test-input", 30
    with tenant_execution_scope(60), pytest.raises(WorkFlowInvalidUserInputError):
        # Existing message 11 belongs to "existing", not this conversation.
        callback.set_user_input({"node": {"question": "wrong"}}, 11, "", verify_input=False)
    assert json.loads(rows(continued)[1][0].message) == {"input": "blocked"}
    callback.redis_client.set.assert_not_called()


def test_platform_input_prompt_establishes_parent_before_gateway_writeback(continued):
    from bisheng.api.v1.schemas import ChatResponse
    from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.worker.workflow.redis_callback import RedisCallback

    callback = RedisCallback.__new__(RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id = "continued", "flow-b", 7
    callback.source, callback.create_session, callback.new_session = "platform", False, None
    callback._finalize_citation_items = lambda *args, **kwargs: []
    with tenant_execution_scope(60):
        callback.save_chat_message(ChatResponse(type="end", category="input", message={"node_id": "node"}))
        ChatMessageService.add_qa_messages(
            SimpleNamespace(chat_id="continued", flow_id="flow-b", human_message="blocked", answer_message="blocked"),
            continued.user,
            "127.0.0.1",
        )
        assert get_current_tenant_id() == 60
    session, messages = rows(continued)
    assert session.tenant_id == 60
    assert len(messages) == 3 and {m.tenant_id for m in messages} == {60}


async def test_workflow_async_input_update_restores_execution_before_enqueue(continued, monkeypatch, tmp_path):
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    import anyio
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, tenant_execution_scope
    from bisheng.database.models import message
    from bisheng.worker.workflow.redis_callback import RedisCallback

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'moderation.db'}")

    @asynccontextmanager
    async def database():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(message, "get_async_db_session", database)
    await anyio.to_thread.run_sync(intercept, continued)
    with bypass_tenant_filter(), continued.db() as db:
        prompt = continued.messages(
            chat_id="continued",
            flow_id="flow-b",
            user_id=7,
            tenant_id=1,
            is_bot=True,
            type="end",
            category="output_with_input_msg",
            message=json.dumps({"node_id": "node", "key": "question"}),
        )
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        prompt_id = prompt.id
    callback = RedisCallback.__new__(RedisCallback)
    callback.chat_id, callback.workflow_id, callback.user_id, callback.source = "continued", "flow-b", 7, "platform"
    callback.redis_client, callback.workflow_input_key, callback.workflow_expire_time = AsyncMock(), "test-input", 30
    try:
        with tenant_execution_scope(60):
            await callback.async_set_user_input({"node": {"question": "async input"}}, prompt_id, "", verify_input=True)
            assert get_current_tenant_id() == 60
        saved = next(m for m in rows(continued)[1] if m.id == prompt_id)
        assert json.loads(saved.message)["hisValue"] == "async input" and saved.tenant_id == 1
        callback.redis_client.aset.assert_awaited_once()
    finally:
        await engine.dispose()


def test_historic_orphan_history_is_not_repaired_or_migrated(continued):
    from fastapi import HTTPException

    from bisheng.chat_session.application.conversation_persistence import ConversationPersistence
    from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope

    intercept(continued)
    with bypass_tenant_filter(), continued.db() as db:
        db.delete(db.get(continued.sessions, "continued"))
        db.commit()
    with tenant_execution_scope(1), pytest.raises(HTTPException):
        with ConversationPersistence(7, user=continued.user).scope("continued", "flow-b", 7):
            pytest.fail("old orphan rows must not be repaired as part of normal continuation")
    session, messages = rows(continued)
    assert session is None and len(messages) == 2
    assert {m.tenant_id for m in messages} == {1}
