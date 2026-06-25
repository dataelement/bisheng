"""Mock-model E2E runner for 灵思LLM容错 (LLM safety-guardrail fault tolerance).

The safety-guardrail error (aliyun ``data_inspection_failed`` …) is hard to
reproduce against a live model, so the model API is SUBSTITUTED by a scripted
fault model (``ScriptedFaultModel``) while everything else is the REAL code path:
``create_linsight_agent`` → deepagents graph → our resilience middleware →
``astream``. No external middleware (MySQL/Redis/MinIO) is needed — the agent
runs fully in-process with an InMemorySaver + the in-memory FakeWorkspaceBackend.

Scenarios:
  R1  real linsight graph, transient error retried then succeeds (Layer A)
  R2  real linsight graph, main-agent content-filter → astream raises (clean fail)
  R3  real langchain agent w/ subagent-flavoured middleware, content-filter →
      loop ends gracefully with the degrade message (Layer B continue)

Run in a CLEAN subprocess:
    cd src/backend && python test/linsight/_e2e_llm_resilience_runner.py
Prints one JSON object on the last stdout line: {"checks": [...]}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_CHECKS: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    _CHECKS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:200]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {str(detail)[:200]}", flush=True)


def make_exc(cls, *, message="", code=None, body=None, status_code=None):
    exc = cls.__new__(cls)
    exc.message = message
    exc.code = code
    exc.body = body
    if status_code is not None:
        exc.status_code = status_code
    return exc


def _build_model():
    """A BaseChatModel whose calls return scripted AIMessages or raise scripted
    exceptions — so we can inject a content-filter / transient failure exactly
    where the deepagents loop would call the real provider."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import PrivateAttr

    class ScriptedFaultModel(BaseChatModel):
        _script: list = PrivateAttr(default_factory=list)
        _calls: list = PrivateAttr(default_factory=lambda: [0])

        def configure(self, script):
            self._script = list(script)
            self._calls = [0]
            return self

        @property
        def _llm_type(self) -> str:
            return "scripted-fault"

        @property
        def calls(self) -> int:
            return self._calls[0]

        def _next(self):
            i = self._calls[0]
            self._calls[0] += 1
            if not self._script:
                return AIMessage(content="ok")
            item = self._script[min(i, len(self._script) - 1)]
            if isinstance(item, BaseException):
                raise item
            return item

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=self._next())])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=self._next())])

        # deepagents/create_agent will bind_tools; the fake ignores tools and
        # drives purely off the script. Returning a binding keeps ainvoke routing
        # through _agenerate (where the script raises/returns).
        def bind_tools(self, tools, **kwargs):
            return self.bind(**kwargs)

    return ScriptedFaultModel()


def _content_filter_exc():
    import openai

    return make_exc(
        openai.BadRequestError,
        message="Output data may contain inappropriate content",
        code="data_inspection_failed",
        body={"code": "data_inspection_failed", "message": "inappropriate content"},
        status_code=400,
    )


def _timeout_exc():
    import openai

    return make_exc(openai.APITimeoutError, message="request timed out")


async def _build_linsight_agent(model):
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver

    from bisheng.common.services.config_service import ConfigService
    from bisheng.linsight.domain.services import agent_factory

    svid = f"e2e-resilience-{uuid.uuid4().hex[:10]}"
    session_model = type("S", (), {"id": svid, "tenant_id": 1, "user_id": 1, "model": None})()
    # Patch the model (external service) and the merged-config read (get_linsight_conf
    # -> get_all_config pulls the DB layer via Redis, unavailable offline). Returning
    # {} makes get_linsight_conf fall back to LinsightConf defaults (retry_num=3,
    # max_degrade=3). Everything else — the deepagents graph, our resilience
    # middleware, astream — is the real path. (settings is a pydantic model, so we
    # patch the class method, not the instance attribute.)
    with (
        patch.object(agent_factory, "_resolve_model", return_value=model),
        patch.object(ConfigService, "get_all_config", return_value={}),
    ):
        agent = await agent_factory.create_linsight_agent(
            session_model=session_model,
            tools=[],
            model_id=None,
            file_dir=None,
            svid=svid,
            backend=None,  # -> in-memory FakeWorkspaceBackend (no MinIO)
            checkpointer=InMemorySaver(),
        )
    return agent, svid


async def _drive(agent, svid):
    cfg = {"configurable": {"thread_id": svid}, "recursion_limit": 50}
    inp = {"messages": [{"role": "user", "content": "Reply with the single word: done."}]}
    async for _ in agent.astream(inp, config=cfg, stream_mode=["values"], subgraphs=True):
        pass


# --------------------------------------------------------------------------- #
# R1 — transient error retried then succeeds, in the REAL linsight graph
# --------------------------------------------------------------------------- #
async def r1_transient_retry():
    from langchain_core.messages import AIMessage

    model = _build_model().configure(
        [_timeout_exc(), _timeout_exc(), AIMessage(content="done")]  # fail twice, then succeed
    )
    agent, svid = await _build_linsight_agent(model)
    raised = None
    try:
        await _drive(agent, svid)
    except Exception as e:
        raised = e
    record(
        "R1 transient error retried then task continues (Layer A, real graph)",
        raised is None and model.calls >= 3,
        f"raised={type(raised).__name__ if raised else None} model_calls={model.calls}",
    )


# --------------------------------------------------------------------------- #
# R2 — main-agent content-filter → astream raises (clean classified failure)
# --------------------------------------------------------------------------- #
async def r2_main_content_filter_raises():
    model = _build_model().configure([_content_filter_exc()])
    agent, svid = await _build_linsight_agent(model)
    raised = None
    try:
        await _drive(agent, svid)
    except Exception as e:
        raised = e

    # The main middleware must NOT retry a content-filter (exactly 1 call) and
    # must re-raise so the task fails cleanly (no synthetic answer mid-reasoning).
    record(
        "R2 main-agent content-filter raises (no retry, clean fail)",
        raised is not None and model.calls == 1,
        f"raised={type(raised).__name__ if raised else None} model_calls={model.calls}",
    )

    # And the failure classifier turns that raised exception into a precise,
    # frontend-friendly error_type (this is what _handle_task_failure emits).
    if raised is not None:
        from bisheng.common.services.llm_error_classifier import classify_for_event

        try:
            wrapped = RuntimeError(f"Agent task execution failed: {raised}")
            wrapped.__cause__ = raised  # mirror task_exec's `raise ... from e`
            classified = classify_for_event(wrapped)
            record(
                "R2 raised exception classified as content_filter (code 11090)",
                classified.error_type == "content_filter" and classified.error_code == 11090,
                f"error_type={classified.error_type} code={classified.error_code}",
            )
        except Exception as e:
            record("R2 classification", False, f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# R3 — subagent-flavoured middleware degrades a content-filter so a REAL
#      langchain agent loop continues/ends gracefully (Layer B)
# --------------------------------------------------------------------------- #
async def r3_subagent_degrade_continues():
    from langchain.agents import create_agent

    from bisheng.linsight.domain.services.resilience_middleware import (
        _DEGRADE_MESSAGE,
        LinsightModelResilienceMiddleware,
    )

    model = _build_model().configure([_content_filter_exc()])
    sub_mw = LinsightModelResilienceMiddleware(max_retries=2, initial_delay=0.0, max_degrade=3, is_subagent=True)
    agent = create_agent(model=model, tools=[], system_prompt="You are a researcher.", middleware=[sub_mw])

    raised = None
    final = None
    try:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": "research X"}]})
        msgs = result.get("messages", []) if isinstance(result, dict) else []
        final = msgs[-1].content if msgs else None
    except Exception as e:
        raised = e

    record(
        "R3 subagent content-filter degraded → loop continues with synthetic reply (Layer B)",
        raised is None and final == _DEGRADE_MESSAGE,
        f"raised={type(raised).__name__ if raised else None} final={str(final)[:60]!r} calls={model.calls}",
    )


async def main() -> int:
    for name, coro in (
        ("R1", r1_transient_retry),
        ("R2", r2_main_content_filter_raises),
        ("R3", r3_subagent_degrade_continues),
    ):
        try:
            await coro()
        except Exception as e:
            record(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc(file=sys.stderr)
    print(json.dumps({"checks": _CHECKS}))
    return 0 if all(c["ok"] for c in _CHECKS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
