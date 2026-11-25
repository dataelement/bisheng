"""S6: can a `planned` agent and a `direct` agent take turns on ONE checkpoint thread?

Design decision 7 puts every run of a conversation on the same thread. The two
profiles are different compiled graphs: `planned` carries TodoListMiddleware (a
`todos` state channel), `direct` does not. This spike runs planned -> direct ->
planned on one thread with a shared checkpointer and reports, per run, whether it
completed, how many messages the model saw, and what `todos` holds afterwards.

Usage (from src/backend/, deepagents 0.7.x venv):
    <python> scripts/spike_unified_runtime/s6_alternate_profiles_on_one_thread.py
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
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

TODOS = [{"content": "1. 收集资料", "status": "completed"}, {"content": "2. 写报告", "status": "in_progress"}]
CONFIG = {"configurable": {"thread_id": "conversation-1"}}


def planned_script() -> list[AIMessage]:
    return [
        AIMessage(content="", tool_calls=[tool_call("write_todos", {"todos": TODOS}, "p1")]),
        AIMessage(content="planned done"),
    ]


async def run(label: str, agent, model: ScriptedModel, text: str) -> dict:
    try:
        state = await agent.ainvoke({"messages": [("user", text)]}, CONFIG)
    except Exception as exc:  # the spike's whole point is to report this
        return {"run": label, "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {
        "run": label,
        "ok": True,
        "messages_seen_by_first_model_call": len(model.seen[0]),
        "messages_in_state": len(state["messages"]),
        "todos_in_state": state.get("todos"),
        "tools": sorted(model.bound_tool_names),
    }


async def main() -> None:
    saver = MemorySaver()
    report = [{"deepagents": md.version("deepagents")}]

    m1 = ScriptedModel(script=planned_script())
    planned_1 = create_deep_agent(model=m1, middleware=[TodoListMiddleware()], checkpointer=saver)
    report.append(await run("1 planned", planned_1, m1, "写一份报告"))

    m2 = ScriptedModel(script=[AIMessage(content="direct answer")])
    direct = create_deep_agent(model=m2, checkpointer=saver)
    report.append(await run("2 direct", direct, m2, "顺便问一句今天星期几"))

    m3 = ScriptedModel(script=planned_script())
    planned_2 = create_deep_agent(model=m3, middleware=[TodoListMiddleware()], checkpointer=saver)
    report.append(await run("3 planned", planned_2, m3, "继续写报告"))

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
