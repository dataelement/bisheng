# ruff: noqa: RUF001 - Chinese prompt text, full-width punctuation is intended
"""S3c: does a REAL model rewrite its plan when the user steers it mid-run?

S3 proved the plumbing with a scripted model: a message drained from the inbox
before a model call reaches that call. This script measures the part S3 could
not: whether real models then call ``write_todos`` to change the plan.

One trial:
  1. the user asks for a three-step job (collect material, write a report,
     proofread);
  2. the model writes its plan with ``write_todos``;
  3. right after that model call, the script puts "把第 3 步改成做一份 PPT" into
     the inbox, exactly as a user typing during the run would;
  4. the script watches the next few model calls for a ``write_todos`` call.

A trial counts as a success when a later ``write_todos`` call has a third item
that mentions PPT and keeps the first two items' wording, so the production
``_diff_todos`` keeps all three task ids on their rows.

Models come from ``LLMService`` by workbench model id. No endpoint or key is
written here. Run it where the backend can reach its database and models:

    cd src/backend
    .venv/bin/python scripts/spike_unified_runtime/s3c_steer_real_model.py \
        --models 12,15,18 --runs 5
    .venv/bin/python scripts/spike_unified_runtime/s3c_steer_real_model.py --list

The script reads configuration and calls models. It writes nothing to the
database, the object store or Redis.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata as md
import json
import os
import sys
from collections import deque
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from deepagents import create_deep_agent  # noqa: E402
from langchain.agents.middleware.types import AgentMiddleware  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from bisheng.linsight.domain.services import stream_event_mapper as sem  # noqa: E402

IS_07 = tuple(int(x) for x in md.version("deepagents").split(".")[:2]) >= (0, 7)

USER_TASK = "帮我调研国内新能源汽车 2025 年的市场情况。分三步做：第 1 步收集资料，第 2 步写一份分析报告，第 3 步校对报告。先用 write_todos 写出这三步计划，再开始执行。"
STEER_TEXT = "把第 3 步改成做一份 PPT，不用校对了。"
SYSTEM_PROMPT = (
    "你是一个按计划执行任务的助手。先调用 write_todos 写出有编号的待办清单，再逐步执行。"
    "执行过程中用户可能随时发来新消息。用户要求调整计划时，调用 write_todos 更新清单："
    "只改用户要求改的那几项，其余条目的文字保持不变。"
)
MAX_MODEL_CALLS = 8


@tool
def search_web(query: str) -> str:
    """搜索公开网页并返回摘要。"""
    return "2025 年国内新能源乘用车零售约 1280 万辆，渗透率约 53%；头部品牌为比亚迪、吉利、特斯拉中国。（演示数据）"


class _SteerOnce(AgentMiddleware):
    """Inbox drained before each model call; the steer message is queued once,
    right after the model call that first wrote the plan."""

    def __init__(self) -> None:
        self.inbox: deque[str] = deque()
        self.todo_calls: list[list[dict[str, Any]]] = []
        self.model_calls = 0
        self.steer_sent_after_call: int | None = None
        self.steer_seen_by_call: int | None = None

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if self.model_calls >= MAX_MODEL_CALLS:
            raise _EnoughCalls
        drained = []
        while self.inbox:
            drained.append(HumanMessage(content=self.inbox.popleft(), additional_kwargs={"source": "inbox"}))
        if drained and self.steer_seen_by_call is None:
            self.steer_seen_by_call = self.model_calls
        return {"messages": drained} if drained else None

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        self.model_calls += 1
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return None
        for call in last.tool_calls or []:
            if call.get("name") != "write_todos":
                continue
            todos = (call.get("args") or {}).get("todos")
            if isinstance(todos, list):
                self.todo_calls.append([t for t in todos if isinstance(t, dict)])
        if self.todo_calls and self.steer_sent_after_call is None:
            self.inbox.append(STEER_TEXT)
            self.steer_sent_after_call = self.model_calls - 1
        elif len(self.todo_calls) >= 2 and _judge(self.todo_calls)["rewrote_step_3"]:
            raise _EnoughCalls
        return None


class _EnoughCalls(Exception):
    """Stops a trial once its outcome is known, to save model calls."""


def _judge(todo_calls: list[list[dict[str, Any]]]) -> dict[str, Any]:
    first = todo_calls[0]
    verdict: dict[str, Any] = {"rewrote_step_3": False, "kept_steps_1_2": False, "ids_aligned": False}
    for later in todo_calls[1:]:
        if len(later) < 3 or len(first) < 3:
            continue
        if "ppt" not in str(later[2].get("content", "")).lower():
            continue
        verdict["rewrote_step_3"] = True
        verdict["kept_steps_1_2"] = all(later[i].get("content") == first[i].get("content") for i in (0, 1))
        mapper = sem.StreamEventMapper("s3c")
        mapper._diff_todos(first)
        before = [p.task_id for p in mapper.ctx.todos]
        mapper._diff_todos(later)
        verdict["ids_aligned"] = [p.task_id for p in mapper.ctx.todos][:3] == before[:3]
        verdict["plan_after"] = [str(t.get("content", "")) for t in later]
        break
    return verdict


async def _trial(model: Any) -> dict[str, Any]:
    steer = _SteerOnce()
    middleware: list[Any] = [steer]
    if IS_07:
        from langchain.agents.middleware import TodoListMiddleware

        middleware.append(TodoListMiddleware())
    agent = create_deep_agent(model=model, tools=[search_web], system_prompt=SYSTEM_PROMPT, middleware=middleware)
    error = None
    try:
        await agent.ainvoke({"messages": [("user", USER_TASK)]}, config={"recursion_limit": 60})
    except _EnoughCalls:
        pass
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    result: dict[str, Any] = {
        "model_calls": steer.model_calls,
        "write_todos_calls": len(steer.todo_calls),
        "steer_sent_after_call": steer.steer_sent_after_call,
        "steer_seen_by_call": steer.steer_seen_by_call,
        "error": error,
    }
    if not steer.todo_calls:
        result["outcome"] = "never_planned"
        return result
    result["plan_before"] = [str(t.get("content", "")) for t in steer.todo_calls[0]]
    verdict = _judge(steer.todo_calls)
    result.update(verdict)
    if verdict["rewrote_step_3"] and verdict["ids_aligned"]:
        result["outcome"] = "success"
    elif verdict["rewrote_step_3"]:
        result["outcome"] = "rewrote_but_misaligned"
    elif steer.steer_seen_by_call is None:
        result["outcome"] = "run_ended_before_steer_was_read"
    else:
        result["outcome"] = "ignored_steer"
    return result


async def _boot_like_linsight_worker(settings: Any) -> None:
    """Register the same process-local runtimes ``linsight/worker.py`` registers
    before it accepts work. ``LLMService`` refuses to resolve a model without them."""
    from bisheng.core.context.manager import initialize_app_context

    if settings.openfga.enabled:
        from bisheng.api.services.f048_permission_runtime import initialize_f048_worker_runtime
        from bisheng.department.domain.services.department_projection_scope import (
            get_department_projection_scope,
            register_department_projection_runtime_context,
        )
        from bisheng.llm.application.model_provider_projection import get_model_provider_projection_scope
        from bisheng.permission.application.process_runtime import (
            get_f048_process_runtime,
            register_f048_permission_runtime_context,
        )

        await initialize_app_context(settings, instance_role="linsight")

        async def initialize(client: Any) -> Any:
            return await initialize_f048_worker_runtime(
                client,
                external_scopes={
                    "department": get_department_projection_scope(),
                    "llm_model_deletion": get_model_provider_projection_scope(),
                },
            )

        register_f048_permission_runtime_context(initialize)
        register_department_projection_runtime_context()
        await get_f048_process_runtime()
    else:
        await initialize_app_context(config=settings)

    from bisheng.resource_reference.composition import register

    register()


async def _main(args: argparse.Namespace) -> None:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.llm.domain.services import LLMService

    await _boot_like_linsight_worker(settings)
    try:
        set_current_tenant_id(args.tenant_id)
        workbench = await LLMService.get_workbench_llm(tenant_id=args.tenant_id)
        catalog = {
            str(m.id): getattr(m, "display_name", None) or getattr(m, "name", None) or str(m.id)
            for m in workbench.models or []
        }
        if args.list:
            print(json.dumps(catalog, ensure_ascii=False, indent=2))
            return

        model_ids = [x.strip() for x in args.models.split(",") if x.strip()] if args.models else list(catalog)[:3]
        report: dict[str, Any] = {"deepagents": md.version("deepagents"), "runs_per_model": args.runs, "models": {}}
        for model_id in model_ids:
            trials = []
            for _ in range(args.runs):
                model = await LLMService.get_bisheng_linsight_llm(
                    invoke_user_id=args.user_id,
                    model_id=model_id,
                    temperature=settings.get_linsight_conf().default_temperature,
                )
                trials.append(await _trial(model))
                print(f"[{catalog.get(model_id, model_id)}] {trials[-1]['outcome']}", file=sys.stderr, flush=True)
            report["models"][model_id] = {
                "name": catalog.get(model_id, model_id),
                "success": sum(t["outcome"] == "success" for t in trials),
                "runs": len(trials),
                "trials": trials,
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await close_app_context()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", default="", help="comma-separated workbench model ids; default: first three")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--list", action="store_true", help="print the workbench model ids and exit")
    asyncio.run(_main(parser.parse_args()))
