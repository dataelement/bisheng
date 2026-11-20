"""Daily mode: the chat entries register a conversation for long-term memory only on the login-state path (F132 T049, AC-10)."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from test.workstation.memory_support import (  # noqa: F401  (fixtures)
    CHAT_ID,
    USER_1,
    cursor,
    login_user,
    memory,
    memory_db,
    memory_runtime_config,
)


# --------------------------------------------------------------------------- registration
async def test_ac10_login_endpoint_registers_the_conversation(memory, monkeypatch):
    """AC-10: the login-state chat endpoint hands the service a register callable that opens the session."""
    from bisheng.workstation.api.endpoints import chat as chat_endpoint

    captured = {}

    async def _fake_stream(request, data, login_user, **kwargs):
        captured.update(kwargs)
        return "resp"

    monkeypatch.setattr(chat_endpoint, "stream_chat_completion", _fake_stream)
    from test.workstation.memory_support import seed_user

    seed_user(memory.db)
    assert await chat_endpoint.chat_completions(MagicMock(), SimpleNamespace(), login_user()) == "resp"
    assert cursor(memory.db) is None
    await captured["memory_register"](CHAT_ID)
    row = cursor(memory.db)
    assert row is not None and row.user_id == USER_1 and row.eligible


def test_ac10_open_api_entry_passes_no_register():
    """AC-10: the open-API daily entry calls the same service function without a register callable."""
    from bisheng.open_endpoints.api.endpoints import workstation as open_ws

    source = inspect.getsource(open_ws.chat_completions)
    assert "stream_chat_completion(" in source
    assert "memory_register" not in source


async def test_ac10_initialize_registers_before_the_question_row(monkeypatch):
    """AC-40/AC-10: registration runs after the conversation exists and before this turn's question row."""
    from bisheng.workstation.domain.services import chat_service

    order = []
    model = SimpleNamespace(id="m1", displayName="stub")
    monkeypatch.setattr(
        chat_service.WorkStationService, "aget_config", AsyncMock(return_value=SimpleNamespace(models=[]))
    )
    # 3.1: the selectable models come from the user's visible workbench models.
    from bisheng.dsh.domain.services import model_catalog

    monkeypatch.setattr(model_catalog, "user_workbench_models", AsyncMock(return_value=[model]))
    monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", AsyncMock())
    monkeypatch.setattr(chat_service.telemetry_service, "log_event", AsyncMock())

    async def _get_one(chat_id):
        return SimpleNamespace(chat_id=chat_id, user_id=USER_1, name="New Chat")

    monkeypatch.setattr(chat_service.MessageSessionDao, "async_get_one", _get_one)
    monkeypatch.setattr(chat_service, "promote_chat_attachments", AsyncMock())
    # skip_llm (a blocked input) also flags the session row since 3.1.
    monkeypatch.setattr(chat_service, "mark_session_content_violation", MagicMock())

    async def _insert(row):
        order.append(("question", row.chat_id))
        row.id = 5
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", _insert)

    async def _register(chat_id):
        order.append(("register", chat_id))

    data = SimpleNamespace(model="m1", conversationId=None, files=None, text="hi", project_id=None)
    out = await chat_service._agent_initialize_chat(data, login_user(), skip_llm=True, memory_register=_register)
    chat_id = out[1].chat_id
    assert order == [("register", chat_id), ("question", chat_id)]
    # Without a register callable (open API, blocked input) nothing is registered.
    order.clear()
    await chat_service._agent_initialize_chat(data, login_user(), skip_llm=True)
    assert [k for k, _ in order] == ["question"]
