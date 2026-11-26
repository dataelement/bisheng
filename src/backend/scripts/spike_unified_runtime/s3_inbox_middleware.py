"""S3 (mechanism half): can a user message be injected into a RUNNING agent?

An `InboxMiddleware` drains a Redis list before every model call and appends the
drained texts to the conversation as HumanMessages. The spike pushes a message
into the inbox while the run is between its first and second model call, then
checks:
  1. the second model call receives the injected HumanMessage, in order, after
     the tool result of the first call;
  2. the injected message is part of the final graph state (so a checkpoint
     keeps it);
  3. a message pushed after the LAST model call is NOT lost: it stays in the
     inbox for the next run to pick up.

The model is scripted, so this proves the plumbing only. Whether a real model
then rewrites its todo list is a separate measurement (needs an LLM endpoint).

Usage (from src/backend/):
    <python> scripts/spike_unified_runtime/s3_inbox_middleware.py
"""

from __future__ import annotations

import asyncio
import importlib.metadata as md
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))

import fakeredis
from _scripted_model import ScriptedModel, tool_call
from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

VERSION = md.version("deepagents")
IS_07 = tuple(int(x) for x in VERSION.split(".")[:2]) >= (0, 7)
INBOX_KEY = "spike:inbox:thread-1"


class InboxMiddleware(AgentMiddleware):
    """Drain the per-thread inbox into the message list before each model call."""

    def __init__(self, redis_client: Any, key: str) -> None:
        self.redis = redis_client
        self.key = key

    def _drain(self) -> list[HumanMessage]:
        drained: list[HumanMessage] = []
        while True:
            raw = self.redis.lpop(self.key)
            if raw is None:
                return drained
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            drained.append(HumanMessage(content=text, additional_kwargs={"source": "inbox"}))

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        drained = self._drain()
        return {"messages": drained} if drained else None

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)


TODOS = [
    {"content": "1. 收集资料", "status": "in_progress"},
    {"content": "2. 写报告", "status": "pending"},
]
SCRIPT = [
    AIMessage(content="", tool_calls=[tool_call("write_todos", {"todos": TODOS}, "c1")]),
    AIMessage(content="", tool_calls=[tool_call("ls", {"path": "/"}, "c2")]),
    AIMessage(content="done"),
]


def describe(messages: list[Any]) -> list[str]:
    out = []
    for m in messages:
        kind = type(m).__name__.replace("Message", "")
        if isinstance(m, ToolMessage):
            out.append(f"Tool({m.name})")
        elif isinstance(m, AIMessage) and m.tool_calls:
            out.append(f"AI->{m.tool_calls[0]['name']}")
        elif kind == "System":
            out.append("System")
        else:
            out.append(f"{kind}:{str(m.content)[:24]}")
    return out


async def main() -> None:
    redis_client = fakeredis.FakeRedis()

    def on_call(index: int) -> None:
        # Simulate the user typing while the agent is busy:
        #  - during model call #0 -> must reach model call #1
        #  - during model call #2 (the last one) -> must stay queued
        if index == 0:
            redis_client.rpush(INBOX_KEY, "第 2 步改成写 PPT")
        if index == 2:
            redis_client.rpush(INBOX_KEY, "这条在最后一次模型调用期间发出")

    model = ScriptedModel(script=SCRIPT, on_call=on_call)
    middleware: list[Any] = [InboxMiddleware(redis_client, INBOX_KEY)]
    if IS_07:
        middleware.append(TodoListMiddleware())
    agent = create_deep_agent(model=model, middleware=middleware)

    final_state = await agent.ainvoke({"messages": [("user", "写一份报告")]})

    call1 = describe(model.seen[1])
    injected_in_call1 = any("改成写 PPT" in s for s in call1)
    order_ok = injected_in_call1 and call1.index("Tool(write_todos)") < next(
        i for i, s in enumerate(call1) if "改成写 PPT" in s
    )
    in_state = any(isinstance(m, HumanMessage) and "改成写 PPT" in str(m.content) for m in final_state["messages"])
    leftover = [x.decode() for x in redis_client.lrange(INBOX_KEY, 0, -1)]

    print(
        json.dumps(
            {
                "deepagents": VERSION,
                "model_calls": len(model.seen),
                "call_1_input": call1,
                "check_1_injected_before_next_model_call": injected_in_call1 and order_ok,
                "check_2_injected_message_in_final_state": in_state,
                "check_3_late_message_still_queued": leftover == ["这条在最后一次模型调用期间发出"],
                "inbox_leftover": leftover,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
