"""Daily mode: resident memory and memory tools per turn (F132 T049).

Covers AC-03, AC-10, AC-27, AC-28, AC-51, AC-61. The stream body of
``_agent_stream_chat_completion`` runs for real; the model is a scripted fake.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import SystemMessage

from bisheng.memory.domain.ports import SCENE_ASSISTANT
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.resident import RESIDENT_HEADER
from test.workstation.memory_support import (  # noqa: F401  (fixtures)
    CHAT_ID,
    USER_1,
    cursor,
    disable_my_memory,
    login_user,
    make_ctx,
    memory,
    memory_db,
    memory_runtime_config,
    metric_total,
    register,
    run_turn,
    stream_env,
)

MEMORY_TOOLS = {"memory_write", "memory_search"}


async def _remember(memory, content="用户偏好用中文回答", scene="daily", chat_id="other-chat", type_="preference"):
    return await memory.service.write(make_ctx(scene=scene, chat_id=chat_id), "remember", content=content, type=type_)


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
        chat_service.WorkStationService, "aget_config", AsyncMock(return_value=SimpleNamespace(models=[model]))
    )
    from bisheng.common.services.config_service import settings as enterprise_settings

    assert not enterprise_settings.dsh.enabled  # default: workbench models come from the config
    monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", AsyncMock())
    monkeypatch.setattr(chat_service.telemetry_service, "log_event", AsyncMock())

    async def _get_one(chat_id):
        return SimpleNamespace(chat_id=chat_id, user_id=USER_1, name="New Chat")

    monkeypatch.setattr(chat_service.MessageSessionDao, "async_get_one", _get_one)
    monkeypatch.setattr(chat_service, "promote_chat_attachments", AsyncMock())

    async def _insert(row):
        order.append(("question", row.chat_id))
        row.id = 5
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", _insert)

    async def _register(chat_id):
        order.append(("register", chat_id))

    data = SimpleNamespace(model="m1", conversationId=None, files=None, text="hi")
    out = await chat_service._agent_initialize_chat(data, login_user(), skip_llm=True, memory_register=_register)
    chat_id = out[1].chat_id
    assert order == [("register", chat_id), ("question", chat_id)]
    # Without a register callable (open API, blocked input) nothing is registered.
    order.clear()
    await chat_service._agent_initialize_chat(data, login_user(), skip_llm=True)
    assert [k for k, _ in order] == ["question"]


# --------------------------------------------------------------------------- injection and tools
async def test_ac51_ac28_enabled_turn_gets_resident_block_and_two_tools(memory, stream_env):
    """AC-51, AC-28: an enabled turn carries the resident block in the system prompt and both memory tools."""
    await _remember(memory)
    chunks = await run_turn(stream_env)
    assert stream_env.state.prompts, "tool branch expected: memory tools make the tool list non-empty"
    prompt = stream_env.state.prompts[0]
    assert prompt.startswith("你是助手。")
    assert RESIDENT_HEADER in prompt and "用户偏好用中文回答" in prompt
    assert MEMORY_TOOLS <= set(stream_env.state.tool_names[0])
    assert any('"final": true' in c for c in chunks)


async def test_ac03_item_written_in_another_scene_is_resident_in_a_new_daily_chat(memory, stream_env):
    """AC-03: an item remembered inside an assistant shows up in the resident block of a fresh daily chat."""
    await _remember(memory, content="用户在杭州工作", scene=SCENE_ASSISTANT, chat_id="assistant-chat", type_="fact")
    await run_turn(stream_env)
    assert "用户在杭州工作" in stream_env.state.prompts[0]


async def test_ac10_service_called_without_register_has_no_memory(memory, stream_env):
    """AC-10: the open-API path (service called directly, no register) neither injects nor offers tools,
    even when the conversation was registered by a login-state turn earlier."""
    await _remember(memory)
    await register(memory.db)
    await run_turn(stream_env, registered=False)
    assert not stream_env.state.prompts  # no tools -> direct branch
    sent = stream_env.state.llm_messages[0]
    assert all(RESIDENT_HEADER not in str(getattr(msg, "content", "")) for msg in sent)


async def test_ac27_my_memory_off_no_tools_no_resident(memory, stream_env):
    """AC-27: with "my memory" off the model gets neither the memory tools nor the resident block."""
    await _remember(memory)
    await register(memory.db)
    await disable_my_memory()
    await run_turn(stream_env)
    assert not stream_env.state.prompts
    sent = stream_env.state.llm_messages[0]
    assert all(RESIDENT_HEADER not in str(getattr(msg, "content", "")) for msg in sent)


async def test_ac27_user_tools_keep_working_without_memory_tools(memory, stream_env):
    """AC-27: memory off with user tools on: tool branch runs, the memory tools are absent."""
    from langchain_core.tools import StructuredTool

    async def _web(q: str) -> str:
        return "ok"

    stream_env.state.user_tools = [StructuredTool.from_function(coroutine=_web, name="web_search", description="d")]
    await register(memory.db)
    await disable_my_memory()
    await run_turn(stream_env)
    assert stream_env.state.tool_names[0] == ["web_search"]
    assert RESIDENT_HEADER not in (stream_env.state.prompts[0] or "")


async def test_ac51_direct_branch_also_gets_resident(memory, stream_env, monkeypatch):
    """AC-51: the no-tools branch (here: memory tools failed to build) still carries the resident block."""
    from bisheng.workstation.domain.services import daily_memory

    def _boom(*_a, **_k):
        raise RuntimeError("tool factory down")

    monkeypatch.setattr(daily_memory, "build_memory_tools", _boom)
    await _remember(memory)
    chunks = await run_turn(stream_env)
    assert not stream_env.state.prompts
    system = [msg for msg in stream_env.state.llm_messages[0] if isinstance(msg, SystemMessage)]
    assert system and RESIDENT_HEADER in system[0].content and "用户偏好用中文回答" in system[0].content
    assert any('"final": true' in c for c in chunks)


async def test_ac61_injection_failure_answer_completes_and_is_counted(memory, stream_env, monkeypatch):
    """AC-61: resident injection failing does not stop the answer; one failure is counted."""

    async def _fail(*_a, **_k):
        raise ConnectionError("redis and db down")

    monkeypatch.setattr(memory.metrics, "mark_read", AsyncMock())
    from bisheng.memory.domain.services import factory

    monkeypatch.setattr(factory.get_resident_service(), "resident", _fail)
    await _remember(memory)
    chunks = await run_turn(stream_env)
    assert any('"final": true' in c for c in chunks)
    from test.workstation.memory_support import answer_rows

    assert len(answer_rows(stream_env.inserted)) == 1
    assert RESIDENT_HEADER not in (stream_env.state.prompts[0] or "")
    assert await metric_total(memory.kv, m.INJECT_FAILED) == 1


@pytest.mark.parametrize("registered", [True, False])
async def test_ac10_registration_failure_never_breaks_the_turn(memory, stream_env, monkeypatch, registered):
    """AC-10/AC-61: a broken memory database never surfaces as a chat error."""
    from bisheng.memory.domain.services.gate import MemoryGate

    monkeypatch.setattr(MemoryGate, "open", AsyncMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(MemoryGate, "resolve", AsyncMock(side_effect=RuntimeError("db down")))
    chunks = await run_turn(stream_env, registered=registered)
    assert any('"final": true' in c for c in chunks)
    assert not stream_env.state.prompts
