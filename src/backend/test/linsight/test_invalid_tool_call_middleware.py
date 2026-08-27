"""Unit tests for LinsightInvalidToolCallRepairMiddleware.

Regression for the 2026-08-27 incident (114, version 6049532c…): the model's
``ask_user`` arguments were not valid JSON (unescaped ``"`` inside a question),
langchain parked the call in ``invalid_tool_calls``, the agent loop ended on an
empty AIMessage and the task closed as ``Task produced no result``.

Covers:
- the LIVE payload is repaired in place (same message id, question text intact),
- unrepairable args → error ToolMessage + one ``jump_to: model`` per user turn,
- mixed valid/invalid turns keep the valid calls and never jump,
- schema-key sanity check rejects json_repair debris for a known tool,
- pass-through when there is nothing to do,
- the prompt/tool docstring carry the no-English-double-quotes rule.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.invalid_tool_call_middleware import (
    INVALID_ARGS_MARKER,
    LinsightInvalidToolCallRepairMiddleware,
    _repair_args,
    build_invalid_tool_call_repair_middleware,
)

# The exact arguments string deepseek-v4-flash emitted in the live session: the
# ``question`` value contains unescaped double quotes (``reason`` is escaped
# correctly) and the second question repeats the ``multiple`` key.
_LIVE_RAW_ARGS = (
    '{"reason": "您提到\\"按照各市要求重新生成\\"，但当前映射表说明没有涉及\\"各市\\"的维度。", '
    '"questions": [{"question": "您说的"按照各市要求"具体是指什么？", '
    '"options": ["按城市/地区分类重新组织映射表", "按照各市的格式规范要求调整文档", "其他（请说明）"], '
    '"multiple": false}, {"question": "重新生成的文档输出格式？", '
    '"options": ["Word（docx）", "Markdown（md）"], "multiple": true, "multiple": false}]}'
)
_CALL_ID = "call_30d0f438439a467da532c3d1"


# --------------------------------------------------------------------------- helpers


def _invalid_ai(raw=_LIVE_RAW_ARGS, name="ask_user", call_id=_CALL_ID, msg_id="lc_run--live", valid_calls=None):
    return AIMessage(
        content="",
        id=msg_id,
        tool_calls=list(valid_calls or []),
        invalid_tool_calls=[{"name": name, "args": raw, "id": call_id, "error": None, "type": "invalid_tool_call"}],
        response_metadata={"finish_reason": "tool_calls"},
    )


def _mw(tools=None, is_subagent=False):
    return build_invalid_tool_call_repair_middleware(tools=tools, is_subagent=is_subagent)


def _state(*messages):
    return {"messages": [HumanMessage(content="上述说明按照各市要求重新生成"), *messages]}


# --------------------------------------------------------------------------- repair


def test_repair_args_recovers_live_payload_intact():
    args = _repair_args(_LIVE_RAW_ARGS)
    assert isinstance(args, dict)
    assert set(args) == {"reason", "questions"}
    # The question text survives byte-for-byte, quotes included.
    assert args["questions"][0]["question"] == '您说的"按照各市要求"具体是指什么？'
    assert args["questions"][0]["options"][0] == "按城市/地区分类重新组织映射表"
    assert args["questions"][1]["question"] == "重新生成的文档输出格式？"


def test_repair_args_rejects_non_objects_and_garbage():
    assert _repair_args("") is None
    assert _repair_args(None) is None
    assert _repair_args("[1, 2, 3]") is None  # valid JSON, not an object
    assert _repair_args('"just a string"') is None
    assert _repair_args("{}") is None


def test_repair_args_unwraps_double_encoded_object():
    assert _repair_args('"{\\"reason\\": \\"why\\", \\"questions\\": []}"') == {"reason": "why", "questions": []}


async def test_live_payload_is_repaired_in_place_and_routed_to_tools():
    mw = _mw(tools=[agent_factory.ask_user])
    ai = _invalid_ai()
    update = await mw.aafter_model(_state(ai), runtime=None)

    assert update is not None
    assert "jump_to" not in update  # the routing edge now sees tool_calls → tools node
    (new_ai,) = update["messages"]
    assert isinstance(new_ai, AIMessage)
    assert new_ai.id == ai.id  # same id → add_messages replaces, no duplicate start frame
    assert new_ai.invalid_tool_calls == []
    assert len(new_ai.tool_calls) == 1
    tc = new_ai.tool_calls[0]
    assert tc["name"] == "ask_user" and tc["id"] == _CALL_ID and tc["type"] == "tool_call"
    assert tc["args"]["questions"][0]["question"] == '您说的"按照各市要求"具体是指什么？'
    # The original message object is not mutated (model_copy).
    assert ai.tool_calls == [] and len(ai.invalid_tool_calls) == 1


def test_sync_hook_matches_async_hook():
    mw = _mw(tools=[agent_factory.ask_user])
    update = mw.after_model(_state(_invalid_ai()), runtime=None)
    assert update and update["messages"][0].tool_calls[0]["name"] == "ask_user"


# --------------------------------------------------------------------------- nudge


async def test_unrepairable_args_get_error_tool_message_and_one_jump_back_to_model():
    mw = _mw()
    ai = _invalid_ai(raw="reason: 需要确认 questions: [", call_id="call_x")
    update = await mw.aafter_model(_state(ai), runtime=None)

    assert update["jump_to"] == "model"
    (tm,) = update["messages"]
    assert isinstance(tm, ToolMessage)
    assert tm.tool_call_id == "call_x" and tm.name == "ask_user" and tm.status == "error"
    assert INVALID_ARGS_MARKER in tm.content
    assert "ask_user" in tm.content and "中文引号" in tm.content
    # The raw text is echoed back (capped) so the model can see what went wrong.
    assert "reason: 需要确认" in tm.content


async def test_second_unrepairable_call_in_same_turn_does_not_jump_again():
    mw = _mw()
    first_ai = _invalid_ai(raw="{{{", call_id="call_1", msg_id="m1")
    first_update = await mw.aafter_model(_state(first_ai), runtime=None)
    assert first_update["jump_to"] == "model"
    (first_tm,) = first_update["messages"]

    second_ai = _invalid_ai(raw="{{{", call_id="call_2", msg_id="m2")
    second_update = await mw.aafter_model(_state(first_ai, first_tm, second_ai), runtime=None)
    # Still answers the dangling call (transcript stays consistent) but no retry:
    # the no-infinite-loop guarantee — the run ends as it did before this middleware.
    assert "jump_to" not in second_update
    (second_tm,) = second_update["messages"]
    assert second_tm.tool_call_id == "call_2" and INVALID_ARGS_MARKER in second_tm.content


async def test_new_human_turn_re_arms_the_nudge():
    mw = _mw()
    stale_tm = ToolMessage(content=f"old {INVALID_ARGS_MARKER}", tool_call_id="old", name="ask_user", status="error")
    ai = _invalid_ai(raw="{{{", call_id="call_new")
    state = {"messages": [HumanMessage(content="q1"), stale_tm, HumanMessage(content="q2"), ai]}
    update = await mw.aafter_model(state, runtime=None)
    assert update["jump_to"] == "model"


async def test_mixed_valid_and_invalid_calls_keep_valid_and_never_jump():
    mw = _mw()
    valid = {"name": "ls", "args": {"path": "/"}, "id": "call_ok", "type": "tool_call"}
    ai = _invalid_ai(raw="{{{", name="write_file", call_id="call_bad", valid_calls=[valid])
    update = await mw.aafter_model(_state(ai), runtime=None)

    assert "jump_to" not in update  # the edge will run the valid call
    (tm,) = update["messages"]
    assert isinstance(tm, ToolMessage) and tm.tool_call_id == "call_bad" and tm.name == "write_file"


async def test_repaired_call_is_appended_after_existing_valid_calls():
    mw = _mw()
    valid = {"name": "ls", "args": {"path": "/"}, "id": "call_ok", "type": "tool_call"}
    ai = _invalid_ai(raw='{"file_path": "/output/a.md", "content": "x"', name="write_file", valid_calls=[valid])
    update = await mw.aafter_model(_state(ai), runtime=None)
    (new_ai,) = update["messages"]
    assert [tc["id"] for tc in new_ai.tool_calls] == ["call_ok", _CALL_ID]
    assert new_ai.tool_calls[1]["args"] == {"file_path": "/output/a.md", "content": "x"}


# --------------------------------------------------------------------------- schema sanity


async def test_repair_debris_for_known_tool_is_rejected_and_nudged():
    mw = _mw(tools=[agent_factory.ask_user])
    # json_repair turns this into a dict, but its keys are not ask_user's.
    ai = _invalid_ai(raw='{"why": "x", "items": []}', call_id="call_d")
    update = await mw.aafter_model(_state(ai), runtime=None)
    assert update["jump_to"] == "model"
    assert isinstance(update["messages"][0], ToolMessage)


async def test_unknown_tool_is_repaired_without_schema_check():
    mw = _mw(tools=[agent_factory.ask_user])
    ai = _invalid_ai(raw='{"todos": [{"content": "a", "status": "pending"}', name="write_todos", call_id="call_t")
    update = await mw.aafter_model(_state(ai), runtime=None)
    assert "jump_to" not in update
    assert update["messages"][0].tool_calls[0]["args"]["todos"][0]["content"] == "a"


# --------------------------------------------------------------------------- pass-through


async def test_no_invalid_calls_is_a_noop():
    mw = _mw()
    ai = AIMessage(content="", tool_calls=[{"name": "ls", "args": {}, "id": "c", "type": "tool_call"}])
    assert await mw.aafter_model(_state(ai), runtime=None) is None
    assert await mw.aafter_model(_state(AIMessage(content="done")), runtime=None) is None
    assert await mw.aafter_model(_state(ToolMessage(content="x", tool_call_id="c")), runtime=None) is None
    assert await mw.aafter_model({"messages": []}, runtime=None) is None


async def test_invalid_call_without_id_is_ignored():
    mw = _mw()
    ai = AIMessage(
        content="",
        invalid_tool_calls=[
            {"name": "ask_user", "args": "{{{", "id": None, "error": None, "type": "invalid_tool_call"}
        ],
    )
    assert await mw.aafter_model(_state(ai), runtime=None) is None


def test_instance_names_are_role_distinct_and_register_no_tools():
    main, sub = _mw(is_subagent=False), _mw(is_subagent=True)
    assert main.name == "LinsightInvalidToolCallRepairMain"
    assert sub.name == "LinsightInvalidToolCallRepairSub"
    assert main.tools == [] and sub.tools == []
    assert isinstance(main, LinsightInvalidToolCallRepairMiddleware)


# --------------------------------------------------------------------------- prompt


def test_prompt_and_tool_doc_forbid_english_double_quotes_in_ask_user_text():
    prompt = agent_factory._build_linsight_system_prompt(False)
    assert "不要出现英文双引号" in prompt
    assert "中文引号「」" in prompt
    assert "不要使用英文双引号" in agent_factory.ask_user.description


# --------------------------------------------------------------------------- graph wiring


def _scripted_model(script):
    """A minimal chat model that replays ``script`` (AIMessages) call by call —
    same shape as _e2e_llm_resilience_runner's ScriptedFaultModel, trimmed."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult

    class _Scripted(BaseChatModel):
        _script: list = []
        _calls: list = [0]
        _seen: list = []

        @property
        def _llm_type(self) -> str:
            return "scripted"

        def _next(self, messages):
            i = self._calls[0]
            self._calls[0] += 1
            self._seen.append(list(messages))
            return self._script[min(i, len(self._script) - 1)]

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

        def bind_tools(self, tools, **kwargs):
            return self.bind(**kwargs)

    m = _Scripted()
    m._script = list(script)
    m._calls = [0]
    m._seen = []
    return m


def _echo_tool():
    from langchain_core.tools import tool

    @tool
    def echo(text: str) -> str:
        """Echo ``text`` back."""
        return f"echo:{text}"

    return echo


async def test_graph_executes_repaired_call_through_the_real_agent_loop():
    from langchain.agents import create_agent

    echo = _echo_tool()
    broken = AIMessage(
        content="",
        id="ai-1",
        invalid_tool_calls=[
            {
                "name": "echo",
                "args": '{"text": "he said "hi" to me"}',
                "id": "c1",
                "error": None,
                "type": "invalid_tool_call",
            }
        ],
    )
    model = _scripted_model([broken, AIMessage(content="final", id="ai-2")])
    agent = create_agent(model=model, tools=[echo], middleware=[_mw(tools=[echo])])

    result = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1 and tool_msgs[0].tool_call_id == "c1"
    assert tool_msgs[0].content == 'echo:he said "hi" to me'  # the tool really ran on the repaired args
    ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert ai_msgs[0].id == "ai-1" and ai_msgs[0].invalid_tool_calls == [] and ai_msgs[0].tool_calls[0]["id"] == "c1"
    assert result["messages"][-1].content == "final"
    assert model._calls[0] == 2


async def test_graph_nudges_model_once_when_args_cannot_be_repaired():
    from langchain.agents import create_agent

    echo = _echo_tool()
    broken = AIMessage(
        content="",
        id="ai-1",
        invalid_tool_calls=[{"name": "echo", "args": "{{{", "id": "c1", "error": None, "type": "invalid_tool_call"}],
    )
    fixed = AIMessage(
        content="", id="ai-2", tool_calls=[{"name": "echo", "args": {"text": "ok"}, "id": "c2", "type": "tool_call"}]
    )
    model = _scripted_model([broken, fixed, AIMessage(content="final", id="ai-3")])
    agent = create_agent(model=model, tools=[echo], middleware=[_mw(tools=[echo])])

    result = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    # Call 2 was the retry: it saw the corrective ToolMessage for c1 in its prompt.
    assert model._calls[0] == 3
    second_prompt = model._seen[1]
    assert any(
        isinstance(m, ToolMessage) and m.tool_call_id == "c1" and INVALID_ARGS_MARKER in m.content
        for m in second_prompt
    )
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert [t.tool_call_id for t in tool_msgs] == ["c1", "c2"]
    assert tool_msgs[1].content == "echo:ok"
    assert result["messages"][-1].content == "final"


async def test_graph_ends_after_second_unrepairable_call_without_looping():
    from langchain.agents import create_agent

    echo = _echo_tool()

    def _broken(i):
        return AIMessage(
            content="",
            id=f"ai-{i}",
            invalid_tool_calls=[
                {"name": "echo", "args": "{{{", "id": f"c{i}", "error": None, "type": "invalid_tool_call"}
            ],
        )

    model = _scripted_model([_broken(1), _broken(2), _broken(3)])
    agent = create_agent(model=model, tools=[echo], middleware=[_mw(tools=[echo])])

    result = await agent.ainvoke({"messages": [HumanMessage(content="go")]})

    # One nudge, then the loop ends (no third model call) — no infinite retry.
    assert model._calls[0] == 2
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert [t.tool_call_id for t in tool_msgs] == ["c1", "c2"]
