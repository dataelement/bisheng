"""F132 T057: assistant session registration and end of turn (Wave 9).

Covers AC-10, AC-37, AC-42, AC-69. Drives the real ``ChatClient`` message
handler with a real ``AssistantAgent`` on a stub model; the message DAO writes
into the SQLite test database.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import StructuredTool
from sqlmodel import select

from bisheng.api.services import assistant as assistant_service_module
from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1 import callback as callback_module
from bisheng.api.v1.schemas import AssistantInfo, AssistantUpdateReq
from bisheng.common.chat import client as client_module
from bisheng.common.chat.client import ChatClient
from bisheng.common.chat.types import WorkType
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.message import ChatMessage
from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.activity import MemoryActivity
from bisheng.memory.domain.services.consolidation_content import ConsolidationContent
from bisheng.memory.domain.services.consolidator import Consolidator
from test.assistant.memory_support import (
    ASSISTANT_ID,
    build_agent,
    final_reply,
    seed_assistant,
    seed_chat,
    tool_reply,
    wired,  # noqa: F401  (pytest fixture)
)
from test.memory.conftest import (  # noqa: F401  (pytest fixtures)
    TENANT_A,
    USER_1,
    USER_2,
    audit_rows,
    details,
    index,
    kv,
    llm,
    make_ctx,
    memory_db,
    memory_runtime_config,
    service,
    tenant_ctx,
)

PUBLIC_ASSISTANT_ID = "0f8b5d7e9a6c4b3d8e2f1a0b9c8d7e6f"


class FakeWebSocket:
    def __init__(self):
        self.frames: list[dict] = []
        self.headers: dict = {}
        self.client = SimpleNamespace(host="127.0.0.1")

    async def send_json(self, data):
        self.frames.append(data)

    async def send_text(self, data):
        self.frames.append({"text": data})

    async def close(self, *a, **k):
        pass


@pytest.fixture
def sqlite_messages(wired, monkeypatch):  # noqa: F811
    """ChatMessageDao.insert_one writes into the SQLite test database (client and callback)."""

    def insert_one(row):
        with wired.db.session() as s:
            s.add(row)
            s.commit()
            s.refresh(row)
        return row

    monkeypatch.setattr(client_module.ChatMessageDao, "insert_one", staticmethod(insert_one))
    monkeypatch.setattr(callback_module.ChatMessageDao, "insert_one", staticmethod(insert_one))
    monkeypatch.setattr(client_module.ChatMessageDao, "get_messages_by_chat_id", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(client_module, "save_message_citations", AsyncMock())
    return wired


def _cursor(db, chat_id):
    with db.session() as s:
        return s.get(MemorySessionCursor, chat_id)


def _cursors(db):
    with db.session() as s:
        return list(s.exec(select(MemorySessionCursor)).all())


async def _logged_in_register(monkeypatch, chat_id, user_id=USER_1):
    """Run the real logged-in assistant WebSocket endpoint and return the callable it injects."""
    from bisheng.api.v1 import assistant as assistant_api

    captured = {}

    async def _dispatch(*args, **kwargs):
        captured["args"], captured["kwargs"] = args, kwargs

    monkeypatch.setattr(assistant_api, "require_business_action", AsyncMock())
    monkeypatch.setattr(assistant_api.chat_manager, "dispatch_client", _dispatch)
    login = SimpleNamespace(user_id=user_id, tenant_id=TENANT_A)
    await assistant_api.chat(assistant_id=ASSISTANT_ID, websocket=FakeWebSocket(), chat_id=chat_id, login_user=login)
    return captured["kwargs"].get("memory_register"), login


def _client(chat_id, memory_register=None, user_id=USER_1, login=None):
    client = ChatClient(
        request=MagicMock(),
        client_key="ck-1",
        client_id=ASSISTANT_ID,
        chat_id=chat_id,
        user_id=user_id,
        login_user=login or SimpleNamespace(user_id=user_id),
        work_type=WorkType.GPTS,
        websocket=FakeWebSocket(),
    )
    # As ChatManager.dispatch_client does: only logged-in endpoints hand one over.
    client.memory_register = memory_register
    # A non-empty history skips the DB history load and the new-session bookkeeping.
    client.chat_history = [{"message": "{}", "category": "system", "remark": ""}]
    return client


def _stub_assistant_lookup(monkeypatch):
    assistant = SimpleNamespace(id=ASSISTANT_ID, status=1, name="差旅助手", prompt="p", max_token=32000, desc="")
    monkeypatch.setattr(client_module.AssistantDao, "get_one_assistant", staticmethod(lambda _id: assistant))
    monkeypatch.setattr(client_module.AssistantAgent, "init_assistant", AsyncMock())
    from bisheng.database.models.assistant import AssistantStatus

    assistant.status = AssistantStatus.ONLINE.value


async def _switch(client, chat_id):
    await client.handle_gpts_message({"inputs": {"data": {"id": ASSISTANT_ID, "chatId": chat_id}}})


async def test_ac10_logged_in_connection_registers_on_chat_id_and_on_switch(wired, tenant_ctx, monkeypatch):  # noqa: F811
    """AC-10 (R2): the logged-in endpoint injects a register callable; the client calls it
    when the chat id is known and again after switching to another chat."""
    tenant_ctx(TENANT_A)
    seed_assistant(wired.db, enabled=True)
    register, _ = await _logged_in_register(monkeypatch, "chat-a1")
    assert callable(register)
    _stub_assistant_lookup(monkeypatch)
    client = _client("chat-a1", register)

    await client.init_gpts_agent()
    assert _cursor(wired.db, "chat-a1").user_id == USER_1

    await _switch(client, "chat-a2")
    assert client.chat_id == "chat-a2"
    assert _cursor(wired.db, "chat-a2").user_id == USER_1


async def test_ac10_logged_in_register_refuses_other_users_chat(wired, tenant_ctx, monkeypatch):  # noqa: F811
    """AC-10 (decision 6): the injected callable cannot register someone else's session."""
    tenant_ctx(TENANT_A)
    seed_chat(wired.db, chat_id="chat-of-2", owner=USER_2)
    register, _ = await _logged_in_register(monkeypatch, "chat-of-2", user_id=USER_1)
    await register("chat-of-2")
    assert _cursor(wired.db, "chat-of-2") is None


async def test_ac10_guest_connection_never_registers(wired, tenant_ctx, monkeypatch):  # noqa: F811
    """AC-10: the guest (public link) endpoint injects nothing; switching never registers."""
    from bisheng.public_endpoints.api.endpoints import assistant as public_api

    tenant_ctx(TENANT_A)
    captured = {}

    @asynccontextmanager
    async def _public_execution(*a, **k):
        yield SimpleNamespace(operator=SimpleNamespace(user_id=USER_1), session_subject=object())

    async def _dispatch(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(public_api, "public_execution", _public_execution)
    monkeypatch.setattr(public_api.PublishedAssistantService, "validate_websocket_session", AsyncMock())
    monkeypatch.setattr(public_api.chat_manager, "dispatch_client", _dispatch)
    await public_api.assistant_ws(websocket=FakeWebSocket(), assistant_id=PUBLIC_ASSISTANT_ID, chat_id="g1")
    assert "session_subject" in captured and captured.get("memory_register") is None

    _stub_assistant_lookup(monkeypatch)
    client = _client("g1", captured.get("memory_register"))
    await client.init_gpts_agent()
    await _switch(client, "g2")
    assert _cursors(wired.db) == []


async def test_ac10_open_api_connection_never_registers(wired, tenant_ctx, monkeypatch):  # noqa: F811
    """AC-10: the open API endpoint injects nothing either."""
    from bisheng.open_endpoints.api.endpoints import assistant as open_api

    tenant_ctx(TENANT_A)
    captured = {}

    @asynccontextmanager
    async def _watch(*a, **k):
        yield

    async def _dispatch(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(open_api, "get_open_api_operator", lambda: SimpleNamespace(user_id=USER_1))
    monkeypatch.setattr(open_api, "get_current_open_api_principal", lambda: object())
    monkeypatch.setattr(open_api, "session_subject_from_principal", lambda p: object())
    monkeypatch.setattr(open_api.PublishedAssistantService, "validate_websocket_session", AsyncMock())
    monkeypatch.setattr(open_api, "watch_websocket_credential", _watch)
    monkeypatch.setattr(open_api.chat_manager, "dispatch_client", _dispatch)
    await open_api.chat(websocket=FakeWebSocket(), assistant_id=ASSISTANT_ID, chat_id="o1")
    assert "message_admission" in captured and captured.get("memory_register") is None

    _stub_assistant_lookup(monkeypatch)
    client = _client("o1", captured.get("memory_register"))
    await client.init_gpts_agent()
    await _switch(client, "o2")
    assert _cursors(wired.db) == []


async def _client_with_agent(monkeypatch, wired, replies, chat_id="chat-a1", tools=None):  # noqa: F811
    register, login = await _logged_in_register(monkeypatch, chat_id)
    client = _client(chat_id, register, login=login)
    agent, model = await build_agent("function call", replies, chat_id=chat_id, tools=tools)
    client.gpts_agent = agent
    client.db_assistant = agent.assistant
    return client, agent, model


def _answers(db, chat_id):
    with db.session() as s:
        return list(
            s.exec(select(ChatMessage).where(ChatMessage.chat_id == chat_id, ChatMessage.category == "answer")).all()
        )


async def test_ac37_answer_persisted_binds_turn_and_marks_pending(sqlite_messages, tenant_ctx, monkeypatch):
    """AC-37: after the answer row is written the turn is bound to it and the session is pending."""
    tenant_ctx(TENANT_A)
    db = sqlite_messages.db
    seed_assistant(db, enabled=True)
    seed_chat(db)
    client, agent, _ = await _client_with_agent(monkeypatch, sqlite_messages, [final_reply("function call", "答复")])

    await client.handle_gpts_message({"inputs": {"input": "你好"}})

    (answer,) = _answers(db, "chat-a1")
    cursor = _cursor(db, "chat-a1")
    assert cursor.state == "pending" and cursor.last_message_id == answer.id
    ctx = agent.memory_turn.ctx if agent.memory_turn else None
    assert ctx is None  # cleared once the turn ended
    with db.session() as s:
        from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord

        (record,) = s.exec(select(MemoryTurnRecord)).all()
    assert record.message_id == answer.id and record.chat_id == "chat-a1"


async def test_ac37_interrupted_answer_binds_and_marks_pending(sqlite_messages, tenant_ctx, monkeypatch):
    """AC-37: a stopped turn (break answer persisted) is bound and marked pending as well."""
    tenant_ctx(TENANT_A)
    db = sqlite_messages.db
    seed_assistant(db, enabled=True)
    seed_chat(db)
    started = asyncio.Event()

    async def _slow(query: str) -> str:
        started.set()
        await asyncio.sleep(30)
        return "never"

    slow = StructuredTool.from_function(coroutine=_slow, name="slow_tool", description="slow")
    client, _, _ = await _client_with_agent(
        monkeypatch, sqlite_messages, [tool_reply("function call", "slow_tool", {"query": "x"})], tools=[slow]
    )

    task = asyncio.create_task(client.handle_gpts_message({"inputs": {"input": "慢慢来"}}))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (answer,) = _answers(db, "chat-a1")
    assert answer.remark == "break_answer"
    cursor = _cursor(db, "chat-a1")
    assert cursor.state == "pending" and cursor.last_message_id == answer.id
    with db.session() as s:
        from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord

        (record,) = s.exec(select(MemoryTurnRecord)).all()
    assert record.message_id == answer.id


async def test_ac37_failed_turn_still_ends_turn(sqlite_messages, tenant_ctx, monkeypatch):
    """AC-37 (R2): the error branch persists no answer but still ends the turn."""
    tenant_ctx(TENANT_A)
    db = sqlite_messages.db
    seed_assistant(db, enabled=True)
    seed_chat(db)
    client, _, _ = await _client_with_agent(monkeypatch, sqlite_messages, [RuntimeError("model endpoint down")])
    await client.handle_gpts_message({"inputs": {"input": "你好"}})

    assert _answers(db, "chat-a1") == []
    with db.session() as s:
        question_id = s.exec(select(ChatMessage.id).where(ChatMessage.category == "question")).one()
    cursor = _cursor(db, "chat-a1")
    assert cursor.state == "pending" and cursor.last_message_id == question_id


async def test_ac41_disabled_turn_advances_watermark(sqlite_messages, tenant_ctx, monkeypatch):
    """AC-41 (decision 7): a turn with memory off moves the watermark past itself."""
    tenant_ctx(TENANT_A)
    db = sqlite_messages.db
    seed_assistant(db, enabled=False)
    seed_chat(db)
    client, _, _ = await _client_with_agent(monkeypatch, sqlite_messages, [final_reply("function call")])

    await client.handle_gpts_message({"inputs": {"input": "你好"}})

    (answer,) = _answers(db, "chat-a1")
    cursor = _cursor(db, "chat-a1")
    assert cursor.watermark_message_id == answer.id and cursor.state != "pending"


async def test_ac37_ac42_assistant_session_consolidated_after_quiet_period(
    sqlite_messages,
    tenant_ctx,
    monkeypatch,
    service,
    kv,
    llm,  # noqa: F811
):
    """AC-37, AC-42: an assistant session becomes due after the quiet period and its turn is
    consolidated into an item marked with the assistant as source."""
    tenant_ctx(TENANT_A)
    db = sqlite_messages.db
    seed_assistant(db, enabled=True)
    seed_chat(db)
    client, _, _ = await _client_with_agent(monkeypatch, sqlite_messages, [final_reply("function call", "好的")])
    await client.handle_gpts_message({"inputs": {"input": "我常驻杭州，出差一般去北京"}})

    now = datetime.now()
    quiet, ttl = timedelta(minutes=30), timedelta(minutes=10)
    assert (TENANT_A, USER_1) not in await MemoryActivity.due_users(now, quiet, ttl)
    later = now + timedelta(hours=1)
    assert (TENANT_A, USER_1) in await MemoryActivity.due_users(later, quiet, ttl)

    llm.answers = [json.dumps({"candidates": [{"content": "用户常驻杭州", "type": "fact"}]}, ensure_ascii=False)]
    consolidator = Consolidator(
        service=service, kv=kv, metrics=m.MemoryMetrics(kv), content_fn=ConsolidationContent(llm)
    )
    with db.session() as s:
        row = s.get(MemorySessionCursor, "chat-a1")
        row.last_activity_at = now - timedelta(hours=1)
        s.add(row)
        s.commit()
    await consolidator.consolidate_user(TENANT_A, USER_1)

    assert "我常驻杭州" in llm.prompts[0]
    async with _db.async_session() as s:
        (item,) = (await s.exec(select(MemoryItem))).all()
    assert (item.content, item.origin, item.source_scene, item.source_app_id) == (
        "用户常驻杭州",
        "auto",
        "assistant",
        ASSISTANT_ID,
    )


def test_ac69_update_request_and_detail_carry_memory_enabled():
    """AC-69: the update request accepts memory_enabled (absent = untouched); details expose it;
    a new assistant has it off."""
    assert AssistantUpdateReq(id="a").memory_enabled is None
    assert AssistantUpdateReq(id="a", memory_enabled=True).memory_enabled is True
    assert Assistant(name="新助手").memory_enabled is False
    assert AssistantInfo(**Assistant(id="a", name="n").model_dump()).memory_enabled is False


@pytest.fixture
def update_env(monkeypatch):
    row = Assistant(id=ASSISTANT_ID, name="差旅助手", tenant_id=TENANT_A, user_id=1, memory_enabled=False)
    saved = []
    monkeypatch.setattr(assistant_service_module.AssistantDao, "get_one_assistant", staticmethod(lambda _id: row))
    monkeypatch.setattr(assistant_service_module.AssistantDao, "update_assistant", staticmethod(saved.append))
    monkeypatch.setattr(assistant_service_module.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(AssistantService, "get_link_info", classmethod(lambda cls, *a: ([], [], [])))
    monkeypatch.setattr(AssistantService, "update_assistant_hook", classmethod(lambda cls, *a: True))
    monkeypatch.setattr(assistant_service_module, "check_business_action", AsyncMock(return_value=False))
    return SimpleNamespace(row=row, saved=saved)


async def test_ac69_editor_can_switch_memory_on_and_off(update_env, monkeypatch):
    """AC-69: an editor turns the switch on; a later update without the field keeps it."""
    monkeypatch.setattr(AssistantService, "check_update_permission_async", AsyncMock())
    login = SimpleNamespace(user_id=1)

    info = await AssistantService.update_assistant(
        MagicMock(), login, AssistantUpdateReq(id=ASSISTANT_ID, memory_enabled=True)
    )
    assert update_env.row.memory_enabled is True and info.memory_enabled is True and update_env.saved

    info = await AssistantService.update_assistant(MagicMock(), login, AssistantUpdateReq(id=ASSISTANT_ID))
    assert info.memory_enabled is True  # absent = untouched

    await AssistantService.update_assistant(
        MagicMock(), login, AssistantUpdateReq(id=ASSISTANT_ID, memory_enabled=False)
    )
    assert update_env.row.memory_enabled is False


async def test_ac69_non_editor_cannot_change_memory_switch(update_env, monkeypatch):
    """AC-69: the existing edit-permission check guards the switch."""
    monkeypatch.setattr(AssistantService, "check_update_permission_async", AsyncMock(side_effect=UnAuthorizedError()))
    with pytest.raises(UnAuthorizedError):
        await AssistantService.update_assistant(
            MagicMock(), SimpleNamespace(user_id=USER_2), AssistantUpdateReq(id=ASSISTANT_ID, memory_enabled=True)
        )
    assert update_env.row.memory_enabled is False and update_env.saved == []


async def test_ac10_debug_run_without_chat_id_has_no_turn_records(wired, tenant_ctx):  # noqa: F811
    """AC-10: a debug run (no chat id) neither registers nor writes turn records."""
    tenant_ctx(TENANT_A)
    seed_assistant(wired.db, enabled=True)
    agent, _ = await build_agent("function call", [final_reply("function call")], chat_id="")
    await agent.run("你好", [])
    await agent.after_answer_persisted(None, False)
    assert _cursors(wired.db) == []
    with wired.db.session() as s:
        from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord

        assert s.exec(select(MemoryTurnRecord)).all() == []
