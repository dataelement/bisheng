"""F132 Wave 0 spike V5 (T006): inject one SystemMessage after trim in the assistant.

Experimental code. Delete after Wave 9.

Builds a real ``AssistantAgent`` (``bisheng/api/services/assistant_agent.py``)
with a stub chat model and runs ``init_agent`` + ``run`` under both executor
kinds: ``ReAct`` (``ConfigurableAssistant`` -> ``get_react_agent_executor``)
and ``function call`` (``langgraph.prebuilt.create_react_agent``). Only the
LLM selection (``init_llm``) and tool loading (``init_tools``) are skipped —
both are DB/config lookups that do not influence how input messages flow.

Findings asserted here:

* The injected SystemMessage, inserted after ``trim_messages`` and before the
  final HumanMessage, reaches the model in both executors. The model then sees
  two system messages: the assistant prompt first, the injected one later.
* ReAct requires the injection to NOT be the last element: ``react_run`` uses
  ``inputs[-1].content`` as the question and ``inputs[:-1]`` as chat_history.
* Without stripping, the injected message stays in ``run()``'s result in both
  executors, and ``client.py:400`` ``result[len(chat_history):-1]`` shifts by
  one: the current HumanMessage leaks into ``new_history``. Stripping it by
  message id before ``run()`` returns restores the original slice exactly.
* ``run()`` appends the query to the caller's ``chat_history`` list in place
  (assistant_agent.py:586), which is why ``len(chat_history)`` in client.py
  already counts the question.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool

from bisheng.api.services.assistant_agent import AssistantAgent

MEMORY_TEXT = "RESIDENT-MEMORY: the user prefers metric units"
MEMORY_MSG_ID = "memory-resident"
PROMPT = "You are the test assistant."


class _StubChatModel(BaseChatModel):
    """Returns scripted replies and records every message list it receives."""

    replies: list[Any]
    received: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        reply = self.replies.pop(0)
        msg = reply if isinstance(reply, AIMessage) else AIMessage(content=reply)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _memory_probe_tool():
    async def _arun(query: str) -> str:
        return "probe-result"

    return StructuredTool.from_function(coroutine=_arun, name="memory_probe", description="probe memory")


def _replies(executor: str) -> list[Any]:
    if executor == "ReAct":
        action = {"action": "memory_probe", "action_input": {"query": "units"}}
        final = {"action": "Final Answer", "action_input": "42 km"}
        return [
            f"Action:\n```\n{json.dumps(action)}\n```",
            f"Action:\n```\n{json.dumps(final)}\n```",
        ]
    return [
        AIMessage(content="", tool_calls=[{"name": "memory_probe", "args": {"query": "units"}, "id": "call_1"}]),
        AIMessage(content="42 km"),
    ]


class _InjectingAgent(AssistantAgent):
    """Prototype of the planned change.

    mode "copy_strip" (recommended): copy the trimmed list, insert before the
    last element, strip by id before run() returns.
    mode "naive": insert into the trimmed list in place, no strip (what a
    straightforward implementation would do).
    """

    mode = "copy_strip"

    async def trim_messages(self, messages):
        trimmed = await super().trim_messages(messages)
        if self.mode == "copy_strip":
            trimmed = list(trimmed)
        # Before the last element: ReAct takes inputs[-1] as the question.
        trimmed.insert(len(trimmed) - 1, SystemMessage(content=MEMORY_TEXT, id=MEMORY_MSG_ID))
        return trimmed

    async def run(self, query, chat_history=None, callback=None):
        result = await super().run(query, chat_history, callback)
        if self.mode == "copy_strip":
            result = [m for m in result if getattr(m, "id", None) != MEMORY_MSG_ID]
        return result


class _NaiveAgent(_InjectingAgent):
    mode = "naive"


class _ToolSpy(AsyncCallbackHandler):
    def __init__(self):
        self.started: list[str] = []

    async def on_tool_start(self, serialized, input_str, **kwargs):
        self.started.append(serialized["name"])


async def _build(executor: str, agent_cls=_InjectingAgent, max_token=32000) -> tuple[AssistantAgent, _StubChatModel]:
    assistant = SimpleNamespace(id="a1", prompt=PROMPT, max_token=max_token, name="t", desc="")
    agent = agent_cls(assistant, chat_id="chat-1", invoke_user_id=7)
    llm = _StubChatModel(replies=_replies(executor), received=[])
    agent.llm = llm
    agent.tools = [_memory_probe_tool()]
    agent.llm_agent_executor = executor
    await agent.init_agent()  # real code: assistant_agent.py:428-458
    return agent, llm


def _client_slice(result, chat_history):
    """Exactly what client.py:397-407 does with run()'s result."""
    answer = result[-1].content
    new_history = result[len(chat_history) : -1]
    kinds = []
    for one in new_history:
        if isinstance(one, AIMessage):
            kinds.append("tool_call")
        elif isinstance(one, ToolMessage):
            kinds.append("tool_result")
        else:
            kinds.append(f"unexpected:{type(one).__name__}")
    return answer, kinds


def _history():
    return [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]


@pytest.mark.parametrize("executor", ["ReAct", "function call"])
async def test_injected_system_message_reaches_model(executor):
    agent, llm = await _build(executor)
    spy = _ToolSpy()
    chat_history = _history()

    result = await agent.run("how far?", chat_history, [spy])

    assert spy.started == ["memory_probe"]  # tool callbacks fire in both executors
    assert len(llm.received) == 2  # tool round + final round
    for messages in llm.received:
        systems = [m for m in messages if isinstance(m, SystemMessage)]
        # The assistant prompt stays first; the injected one is a second system message.
        assert PROMPT in systems[0].content
        assert any(m.content == MEMORY_TEXT for m in systems[1:])
        injected_at = next(i for i, m in enumerate(messages) if m.content == MEMORY_TEXT)
        assert injected_at > 0
    assert result[-1].content == "42 km"


async def _kinds(executor, agent_cls, max_token=32000):
    agent, _ = await _build(executor, agent_cls, max_token)
    history = _history()
    result = await agent.run("how far?", history)
    assert all(getattr(m, "id", None) != MEMORY_MSG_ID for m in result) or agent_cls is _NaiveAgent
    return _client_slice(result, history), len(history), result


async def test_slice_function_call_untrimmed():
    (base, base_hist_len, _) = await _kinds("function call", AssistantAgent)
    # run() appends the question to the caller's list in place (assistant_agent.py:586),
    # so len(chat_history) already counts it and the slice yields the new messages.
    assert base == ("42 km", ["tool_call", "tool_result"]) and base_hist_len == 3

    # Naive in-place insert does NOT shift the slice here, only by accident:
    # trim_messages returns the very same list object when nothing is dropped
    # (assistant_agent.py:572), so the insert also grows the caller's chat_history.
    (naive, naive_hist_len, naive_result) = await _kinds("function call", _NaiveAgent)
    assert naive == base and naive_hist_len == 4
    assert any(getattr(m, "id", None) == MEMORY_MSG_ID for m in naive_result)

    # Recommended copy + strip-by-id: identical to baseline, caller list untouched by the insert.
    (rec, rec_hist_len, _) = await _kinds("function call", _InjectingAgent)
    assert rec == base and rec_hist_len == 3


async def test_slice_function_call_trimmed():
    # max_token=7 makes trim_messages drop the oldest message (a new list is returned).
    (base, _, _) = await _kinds("function call", AssistantAgent, max_token=7)
    # Pre-existing bug, independent of memory: dropping k messages shifts the
    # slice by k, so the tool_call row is lost.
    assert base == ("42 km", ["tool_result"])

    # Naive insert on a trimmed (non-aliased) list: the insert shifts the slice
    # by +1 and cancels the trim's -1 by coincidence, so the output differs from
    # the baseline. With 2 dropped messages it would still be off by one.
    (naive, _, _) = await _kinds("function call", _NaiveAgent, max_token=7)
    assert naive != base and naive == ("42 km", ["tool_call", "tool_result"])

    # Copy + strip restores exactly the baseline behaviour.
    (rec, _, _) = await _kinds("function call", _InjectingAgent, max_token=7)
    assert rec == base


async def test_slice_react():
    # ReAct: react_run appends AgentAction objects + the answer to `inputs`
    # (assistant_agent.py:679-681), and `inputs` IS the caller's chat_history
    # when trim drops nothing. So result is chat_history and the slice is empty:
    # path one never persists ReAct tool calls; only the callback path (V1) does.
    (base, base_hist_len, _) = await _kinds("ReAct", AssistantAgent)
    assert base == ("42 km", []) and base_hist_len == 5

    (naive, _, _) = await _kinds("ReAct", _NaiveAgent)
    assert naive == base

    # Copy + strip breaks the aliasing: the AgentAction now lands in the slice and
    # hits the "unexpected message type" warning branch (client.py:406-407) — it is
    # logged and skipped, nothing extra is persisted.
    (rec, rec_hist_len, _) = await _kinds("ReAct", _InjectingAgent)
    assert rec == ("42 km", ["unexpected:AgentAction"]) and rec_hist_len == 3
