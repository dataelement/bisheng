"""Subagent checkpoints must store message deltas, not the full list per step.

The researcher subagent inherits the main graph's checkpointer. deepagents only
gives it the DeltaChannel-backed DeepAgentState when create_deep_agent receives
an explicit state_schema; otherwise every subagent step writes the whole message
list and one run grows Redis by O(N^2) bytes (~90 MB per researcher on 105).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from deepagents import create_deep_agent
from deepagents.graph import DeepAgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.linsight.domain.services import agent_factory

SUBAGENT_STEPS = 20


class _ScriptedModel(BaseChatModel):
    replies: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=next(self.replies))])


class _RecordingSaver(InMemorySaver):
    def __init__(self):
        super().__init__()
        self.puts: list[tuple[str, bool]] = []

    async def aput(self, config, checkpoint, metadata, new_versions):
        ns = config["configurable"].get("checkpoint_ns", "")
        self.puts.append((ns, "messages" in checkpoint["channel_values"]))
        return await super().aput(config, checkpoint, metadata, new_versions)


@tool
def echo(s: str) -> str:
    """Echo the input back."""
    return s


def _replies():
    yield AIMessage(
        "",
        tool_calls=[{"name": "task", "args": {"description": "dig", "subagent_type": "researcher"}, "id": "t0"}],
    )
    for i in range(SUBAGENT_STEPS):
        yield AIMessage("", tool_calls=[{"name": "echo", "args": {"s": str(i)}, "id": f"e{i}"}])
    yield AIMessage("sub done")
    yield AIMessage("main done")


async def test_subagent_checkpoints_hold_deltas_with_deep_agent_state():
    saver = _RecordingSaver()
    agent = create_deep_agent(
        model=_ScriptedModel(replies=_replies()),
        tools=[echo],
        subagents=[{"name": "researcher", "description": "r", "system_prompt": "r", "tools": [echo]}],
        state_schema=DeepAgentState,
        checkpointer=saver,
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "go"}]},
        {"configurable": {"thread_id": "t"}, "recursion_limit": 500},
    )

    sub_puts = [stored for ns, stored in saver.puts if ns.startswith("tools:")]
    assert len(sub_puts) > SUBAGENT_STEPS
    # Only the first checkpoint and DeltaChannel snapshots carry the full list.
    assert sum(sub_puts) <= 2
    # The subagent's answer still reaches the main graph intact.
    tool_results = [m.content for m in result["messages"] if isinstance(m, ToolMessage)]
    assert "sub done" in tool_results


async def test_factory_passes_deep_agent_state(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name="agent")

    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(SimpleNamespace(), False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q", api_meta=None)

    await agent_factory.create_linsight_agent(session, [])

    assert captured["state_schema"] is DeepAgentState
