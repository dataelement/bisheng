"""S1 + S2 (runtime half): todo channel shape and filesystem tool output.

Run the SAME script under deepagents 0.6.12 and 0.7.x and diff the two outputs.
It answers:
  * does `write_todos` still write a `todos` state delta that arrives in
    stream_mode="updates" with the same shape (what `_diff_todos` consumes)?
  * what do `ls` on an empty dir and `read_file` return (0.7 changed both)?
  * which tools are bound and how long is the system prompt?

Usage (from src/backend/):
    <python> scripts/spike_unified_runtime/s1_todo_and_tool_output.py
"""

from __future__ import annotations

import asyncio
import importlib.metadata as md
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _scripted_model import ScriptedModel, tool_call
from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

VERSION = md.version("deepagents")
IS_07 = tuple(int(x) for x in VERSION.split(".")[:2]) >= (0, 7)

TODOS_V1 = [
    {"content": "1. 收集资料", "status": "in_progress"},
    {"content": "2. 写报告", "status": "pending"},
]
TODOS_V2 = [
    {"content": "1. 收集资料", "status": "completed"},
    {"content": "2. 写报告", "status": "in_progress"},
]

SCRIPT = [
    AIMessage(content="", tool_calls=[tool_call("write_todos", {"todos": TODOS_V1}, "c1")]),
    AIMessage(content="", tool_calls=[tool_call("ls", {"path": "/empty"}, "c2")]),
    AIMessage(
        content="", tool_calls=[tool_call("write_file", {"file_path": "/a.txt", "content": "line1\nline2\n"}, "c3")]
    ),
    AIMessage(content="", tool_calls=[tool_call("read_file", {"file_path": "/a.txt"}, "c4")]),
    AIMessage(content="", tool_calls=[tool_call("write_todos", {"todos": TODOS_V2}, "c5")]),
    AIMessage(content="done"),
]


def build_agent(model: ScriptedModel):
    if IS_07:
        from langchain.agents.middleware import TodoListMiddleware

        return create_deep_agent(model=model, middleware=[TodoListMiddleware()])
    return create_deep_agent(model=model)


async def main() -> None:
    model = ScriptedModel(script=SCRIPT)
    agent = build_agent(model)
    todo_updates = []
    tool_outputs: dict[str, str] = {}

    async for item in agent.astream(
        {"messages": [("user", "写一份报告")]},
        stream_mode=["updates", "values"],
        subgraphs=True,
    ):
        ns, mode, chunk = item
        if mode != "updates" or not isinstance(chunk, dict):
            continue
        for node, delta in chunk.items():
            if not isinstance(delta, dict):
                continue
            if delta.get("todos") is not None:
                todo_updates.append({"ns": list(ns), "node": node, "todos": delta["todos"]})
            for msg in delta.get("messages") or []:
                if isinstance(msg, ToolMessage):
                    tool_outputs[msg.name or "?"] = str(msg.content)

    system_chars = sum(len(str(m.content)) for m in model.seen[0] if isinstance(m, SystemMessage))
    print(
        json.dumps(
            {
                "deepagents": VERSION,
                "langchain": md.version("langchain"),
                "langgraph": md.version("langgraph"),
                "bound_tools": sorted(model.bound_tool_names),
                "system_prompt_chars": system_chars,
                "todo_updates": todo_updates,
                "ls_empty_output": tool_outputs.get("ls"),
                "read_file_output": tool_outputs.get("read_file"),
                "write_todos_output": tool_outputs.get("write_todos"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
