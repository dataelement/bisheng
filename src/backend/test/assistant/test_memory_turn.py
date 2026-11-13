"""F132 T053: per-turn memory handling in ``AssistantAgent`` (Wave 9).

Covers AC-02, AC-10, AC-51, AC-61, AC-71, AC-72, AC-73, AC-74, AC-77. Every test
runs under both executors (ReAct and function call) with a stub chat model.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from loguru import logger
from sqlmodel import select

from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import factory
from bisheng.memory.domain.services import metrics as m
from test.assistant.memory_support import (
    ASSISTANT_ID,
    EXECUTORS,
    build_agent,
    client_slice,
    final_reply,
    has_resident,
    register,
    seed_assistant,
    seed_chat,
    set_switch,
    tool_names,
    tool_reply,
    wired,  # noqa: F401  (pytest fixture)
)
from test.memory.conftest import (  # noqa: F401  (pytest fixtures)
    TENANT_A,
    USER_1,
    USER_2,
    audit_rows,
    counter,
    details,
    index,
    kv,
    make_ctx,
    memory_db,
    memory_runtime_config,
    service,
    tenant_ctx,
)

MEMORY_TOOLS = {"memory_write", "memory_search"}
FACT = "用户出差只坐靠窗座位"


@pytest.fixture
async def enabled_chat(wired, tenant_ctx):
    tenant_ctx(TENANT_A)
    seed_assistant(wired.db, enabled=True)
    seed_chat(wired.db)
    await register()
    return wired


async def _remember(service, make_ctx, text=FACT, user_id=USER_1):
    return await service.write(make_ctx(user_id=user_id), "remember", content=text, type="preference")


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac69_ac71_new_assistant_switch_default_on(executor, wired, tenant_ctx, make_ctx):
    """AC-69, AC-71 (Kunlian integration: new assistants start with memory on): a new assistant
    gets the resident block and the memory tools without the author touching the switch."""
    tenant_ctx(TENANT_A)
    seed_assistant(wired.db)  # column default
    seed_chat(wired.db)
    await register()
    await _remember(wired.service, make_ctx)
    agent, llm = await build_agent(executor, [final_reply(executor)])

    result = await agent.run("你好", [])

    assert result[-1].content == "好的"
    assert any(has_resident(msgs) for msgs in llm.received)
    assert MEMORY_TOOLS <= set(tool_names(agent))


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac51_ac77_enabled_injects_resident_and_tools_without_author_tools(executor, enabled_chat, make_ctx):
    """AC-51, AC-77: switch on + registered: every turn carries the resident block and the
    two memory tools, although the author configured no tool at all."""
    await _remember(enabled_chat.service, make_ctx)
    agent, llm = await build_agent(executor, [final_reply(executor), final_reply(executor)])

    for question in ("第一轮", "第二轮"):
        await agent.run(question, [])
        sent = llm.received[-1]
        assert has_resident(sent) and any(FACT in str(x.content) for x in sent)
        # Injected right before the question (ReAct reads inputs[-1] as the question).
        # (ReAct wraps the question in its own "Question: ..." scratchpad message.)
        assert isinstance(sent[-1], HumanMessage) and question in sent[-1].content
        resident_at = next(i for i, x in enumerate(sent) if FACT in str(x.content))
        assert 0 < resident_at < len(sent) - 1
        assert MEMORY_TOOLS <= set(tool_names(agent))
    if executor == "function call":
        assert MEMORY_TOOLS <= set(llm.bound[-1])
    else:
        assert "memory_write" in sent[0].content  # ReAct lists tools in its system prompt


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac72_ac73_ac74_switch_reread_each_turn_on_same_agent(executor, enabled_chat, make_ctx):
    """AC-72, AC-73, AC-74: the switch is re-read from the database every turn on the same
    AssistantAgent object; off drops resident and tools, on again restores earlier items."""
    await _remember(enabled_chat.service, make_ctx)
    agent, llm = await build_agent(executor, [final_reply(executor)] * 3)

    await agent.run("一", [])
    assert has_resident(llm.received[-1]) and MEMORY_TOOLS <= set(tool_names(agent))

    set_switch(enabled_chat.db, False)
    await agent.run("二", [])
    assert not has_resident(llm.received[-1])
    assert not MEMORY_TOOLS & set(tool_names(agent))

    set_switch(enabled_chat.db, True)
    await agent.run("三", [])
    assert any(FACT in str(x.content) for x in llm.received[-1])
    assert MEMORY_TOOLS <= set(tool_names(agent))


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac74_switch_flip_during_turn_applies_next_turn(executor, enabled_chat, make_ctx):
    """AC-74: a flip while the answer is generated keeps this turn's state."""
    await _remember(enabled_chat.service, make_ctx)

    async def _flip(query: str) -> str:
        set_switch(enabled_chat.db, False)
        return "ok"

    flip = StructuredTool.from_function(coroutine=_flip, name="flip_switch", description="flip")
    agent, llm = await build_agent(
        executor,
        [tool_reply(executor, "flip_switch", {"query": "x"}), final_reply(executor), final_reply(executor)],
        tools=[flip],
    )
    await agent.run("一", [])
    assert all(has_resident(msgs) for msgs in llm.received)  # both model calls of this turn
    await agent.run("二", [])
    assert not has_resident(llm.received[-1])


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac51_resident_survives_history_trim(executor, enabled_chat, make_ctx):
    """AC-51: trimming long history never drops the resident block (inserted after trim)."""
    await _remember(enabled_chat.service, make_ctx)
    agent, llm = await build_agent(executor, [final_reply(executor)], max_token=40)
    history = []
    for i in range(10):
        history += [HumanMessage(content=f"很长的旧问题 {i} " * 5), AIMessage(content=f"很长的旧回答 {i} " * 5)]

    await agent.run("现在的问题", history)

    sent = llm.received[-1]
    assert has_resident(sent)
    assert not any("很长的旧问题 0" in str(x.content) for x in sent)  # trim did happen


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac51_run_result_excludes_injected_message_and_slice_unchanged(executor, enabled_chat, make_ctx):
    """AC-51: run() strips the injected message; the client's slice is the same as without memory."""
    await _remember(enabled_chat.service, make_ctx)

    async def _probe(query: str) -> str:
        return "probe-result"

    probe = StructuredTool.from_function(coroutine=_probe, name="probe", description="probe")
    agent, _ = await build_agent(
        executor, [tool_reply(executor, "probe", {"query": "q"}), final_reply(executor, "42")], tools=[probe]
    )
    history = [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]

    result = await agent.run("how far?", history)

    assert not any(has_resident([x]) for x in result if hasattr(x, "content"))
    answer, kinds = client_slice(result, history)
    assert answer == "42"
    if executor == "function call":
        assert kinds == ["tool_call", "tool_result"]
    else:
        assert kinds == ["unexpected:AgentAction"]  # logged and skipped by the client, as verified in V5
    assert len(history) == 3  # only the question was appended to the caller's list


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac61_inject_failure_turn_completes_and_counts(executor, enabled_chat, make_ctx, monkeypatch, kv):
    """AC-61: a failing resident read still answers, and counts one inject failure."""
    await _remember(enabled_chat.service, make_ctx)

    async def _boom(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(factory.get_resident_service(), "resident", _boom)
    agent, llm = await build_agent(executor, [final_reply(executor, "照常回答")])

    result = await agent.run("你好", [])

    assert result[-1].content == "照常回答"
    assert not has_resident(llm.received[-1])
    assert MEMORY_TOOLS <= set(tool_names(agent))
    assert await counter(kv, TENANT_A, m.INJECT_FAILED) == 1


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac77_reserved_name_author_tool_replaced_with_warning(executor, enabled_chat):
    """AC-77 (design decision 10): an author tool with a memory_ name loses to the built-in one
    and leaves a warning."""

    async def _fake(query: str) -> str:
        return "author tool"

    fake = StructuredTool.from_function(coroutine=_fake, name="memory_write", description="author's own")
    warnings: list[str] = []
    sink = logger.add(lambda msg: warnings.append(str(msg)), level="WARNING")
    try:
        agent, _ = await build_agent(executor, [final_reply(executor)], tools=[fake])
        await agent.run("你好", [])
    finally:
        logger.remove(sink)

    writes = [t for t in agent.tools if t.name == "memory_write"]
    assert len(writes) == 1 and writes[0].description != "author's own"
    assert any("reserved memory_ prefix" in w for w in warnings)


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac02_user_b_cannot_read_user_a_in_same_assistant(executor, enabled_chat, make_ctx):
    """AC-02: two users of one memory-enabled assistant never see each other's items."""
    await _remember(enabled_chat.service, make_ctx, text="用户甲的会员号偏好")
    seed_chat(enabled_chat.db, chat_id="chat-b1", owner=USER_2)
    await register("chat-b1", USER_2)

    search = {"query": "会员号偏好"}
    agent_b, llm_b = await build_agent(
        executor,
        [tool_reply(executor, "memory_search", search), final_reply(executor)],
        chat_id="chat-b1",
        user_id=USER_2,
    )
    await agent_b.run("我的会员号偏好是什么", [])
    seen_b = " ".join(str(x.content) for msgs in llm_b.received for x in msgs)
    assert "用户甲的会员号偏好" not in seen_b

    agent_a, llm_a = await build_agent(executor, [tool_reply(executor, "memory_search", search), final_reply(executor)])
    await agent_a.run("我的会员号偏好是什么", [])
    seen_a = " ".join(str(x.content) for msgs in llm_a.received for x in msgs)
    assert "用户甲的会员号偏好" in seen_a  # positive control


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac10_no_registration_no_memory(executor, wired, tenant_ctx, make_ctx):
    """AC-10: no registration row (guest link, open API, debug run) means memory never works."""
    tenant_ctx(TENANT_A)
    seed_assistant(wired.db, enabled=True)
    seed_chat(wired.db)
    await _remember(wired.service, make_ctx)
    agent, llm = await build_agent(executor, [final_reply(executor)])

    await agent.run("你好", [])

    assert not has_resident(llm.received[-1])
    assert not MEMORY_TOOLS & set(tool_names(agent))
    debug, llm_debug = await build_agent(executor, [final_reply(executor)], chat_id="")
    await debug.run("你好", [])
    assert not has_resident(llm_debug.received[-1])


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac77_memory_write_tool_works_in_assistant(executor, enabled_chat, make_ctx):
    """AC-77: the model can write explicitly through the built-in tool."""
    agent, llm = await build_agent(
        executor,
        [
            tool_reply(
                executor, "memory_write", {"action": "remember", "content": "用户喜欢绿茶", "type": "preference"}
            ),
            final_reply(executor, "记住了"),
        ],
    )
    result = await agent.run("记一下我喜欢绿茶", [])
    assert result[-1].content == "记住了"
    async with _db.async_session() as s:
        items = list((await s.exec(select(MemoryItem))).all())
    assert [(i.content, i.source_scene, i.source_app_id) for i in items] == [
        ("用户喜欢绿茶", "assistant", ASSISTANT_ID)
    ]


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac02_knowing_someone_elses_chat_id_gives_no_memory(executor, enabled_chat, make_ctx):
    """AC-02 / AC-08: user B sends user A's registered chat_id; B gets none of A's memory."""
    await _remember(enabled_chat.service, make_ctx, text="用户甲的会员号偏好")
    agent_b, llm_b = await build_agent(executor, [final_reply(executor)], user_id=USER_2)  # A's chat

    await agent_b.run("你好", [])

    assert not has_resident(llm_b.received[-1])
    assert not MEMORY_TOOLS & set(tool_names(agent_b))


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac10_guest_connection_never_gets_memory(executor, enabled_chat, make_ctx):
    """AC-10: a guest-link / open-API connection (no memory_register) switching to a registered
    chat of the same user id still gets no memory."""
    await _remember(enabled_chat.service, make_ctx)
    agent, llm = await build_agent(executor, [final_reply(executor)])
    agent.memory_allowed = False  # what ChatClient leaves on guest and open-API connections

    await agent.run("你好", [])

    assert not has_resident(llm.received[-1])
    assert not MEMORY_TOOLS & set(tool_names(agent))


def test_resident_message_is_first_and_question_stays_last():
    """Decision 11 / R6: consecutive with the system prompt (Anthropic rejects split system messages)."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from bisheng.api.services import assistant_memory

    turn = assistant_memory.AssistantMemoryTurn()
    turn.resident_text = "以下是关于用户的背景信息"
    inputs = [HumanMessage(content="早"), AIMessage(content="早"), HumanMessage(content="问题")]
    prepared = assistant_memory.prepare_inputs(inputs, turn)
    assert isinstance(prepared[0], SystemMessage) and prepared[0].content == turn.resident_text
    assert prepared[-1].content == "问题" and len(inputs) == 3
