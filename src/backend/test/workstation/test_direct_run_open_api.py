"""F004 decision 14: what a direct run does for Open API daily chat, and the two
behaviours of the legacy daily chat that the direct run took over.

* Open API (AC-39): the run is unattended (no question to a user who is not
  there) and takes over the department lease the send request acquired.
* For every caller: the administrator's workbench system prompt reaches the
  model, and a finished or failed run logs the daily-chat telemetry.

The REAL graph runs with the scripted model of ``test_direct_run``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from bisheng.workstation.domain.services import direct_run
from bisheng.workstation.domain.services.direct_run import DirectRunContext, DirectRunner
from test.workstation.test_direct_run import ASK, TENANT, USER, make_env  # noqa: F401  (fixture)

# The root conftest replaces these two for every test; keep the real ones.
REAL_WORKBENCH_PROMPT = direct_run.workbench_system_prompt
REAL_TELEMETRY = direct_run.log_daily_chat_telemetry


def _system_text(model) -> str:
    first = model.inputs[0]
    return "\n".join(str(m.content) for m in first if isinstance(m, SystemMessage))


class _Telemetry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, ctx: DirectRunContext, started_at: float) -> None:
        assert started_at > 0
        self.calls.append((ctx.run_id, ctx.conversation_id))


async def test_workbench_prompt_reaches_the_model_under_the_platform_rules(make_env):  # noqa: F811
    env = make_env([AIMessage(content="好的")])

    async def prompt() -> str:
        return "回答一律用表格。"

    runner = env.make_runner(workbench_prompt=prompt)
    ctx = await env.submit("你好")

    assert (await env.run(ctx, runner)).status == "finished"

    system = _system_text(env.model)
    assert "# 管理员设定的回答要求" in system
    assert "回答一律用表格。" in system
    # Platform rules come first and win a conflict.
    assert system.index("你是工作台助手") < system.index("# 管理员设定的回答要求")


async def test_no_workbench_prompt_adds_no_section(make_env):  # noqa: F811
    env = make_env([AIMessage(content="好的")])
    ctx = await env.submit("你好")

    assert (await env.run(ctx)).status == "finished"

    assert "管理员设定的回答要求" not in _system_text(env.model)


async def test_telemetry_is_logged_for_finished_and_failed_runs_only(make_env):  # noqa: F811
    telemetry = _Telemetry()

    env = make_env([AIMessage(content="好的")])
    ctx = await env.submit("你好")
    assert (await env.run(ctx, env.make_runner(log_telemetry=telemetry))).status == "finished"
    assert telemetry.calls == [(ctx.run_id, ctx.conversation_id)]

    failed_env = make_env([RuntimeError("provider exploded")])
    failed_ctx = await failed_env.submit("你好")
    assert (await failed_env.run(failed_ctx, failed_env.make_runner(log_telemetry=telemetry))).status == "failed"
    assert telemetry.calls[-1] == (failed_ctx.run_id, failed_ctx.conversation_id)

    # A parked run has not answered yet: nothing is logged for it.
    parked_env = make_env([ASK])
    parked_ctx = await parked_env.submit("帮我挑颜色")
    count = len(telemetry.calls)
    assert (await parked_env.run(parked_ctx, parked_env.make_runner(log_telemetry=telemetry))).status == "waiting"
    assert len(telemetry.calls) == count


async def test_unattended_run_gets_the_no_question_prompt(make_env):  # noqa: F811
    env = make_env([AIMessage(content="按常见做法给出答案。")])
    ctx = await env.submit("帮我挑颜色")
    ctx.unattended = True

    assert (await env.run(ctx)).status == "finished"

    system = _system_text(env.model)
    assert "【无人值守，不提问】" in system
    assert "【何时提问】" not in system


def test_unattended_context_marks_the_session_as_open_api():
    ctx = DirectRunContext(conversation_id="c", run_id="r", tenant_id=TENANT, user_id=USER, unattended=True)
    assert DirectRunner._session(ctx).api_meta == {"channel": "open_api_v2"}
    attended = DirectRunContext(conversation_id="c", run_id="r", tenant_id=TENANT, user_id=USER)
    assert DirectRunner._session(attended).api_meta is None


def test_context_round_trips_the_open_api_fields():
    ctx = DirectRunContext(
        conversation_id="c",
        run_id="r",
        tenant_id=TENANT,
        user_id=USER,
        unattended=True,
        storage_partition="service-account/9/abc",
        execution_lease_id="lease-1",
    )
    again = DirectRunContext.from_dict(ctx.to_dict())
    assert (again.unattended, again.storage_partition, again.execution_lease_id) == (
        True,
        "service-account/9/abc",
        "lease-1",
    )


async def test_department_slot_takes_over_the_lease_of_the_send_request(monkeypatch: pytest.MonkeyPatch):
    from bisheng.department.domain.services.department_flow_service import DepartmentFlowService, SlotOutcome

    held: list[Any] = []

    @asynccontextmanager
    async def hold(login_user, lease_id=None):
        held.append((login_user.user_id, lease_id, "enter"))
        yield SlotOutcome.HELD, SimpleNamespace(lease_id=lease_id)
        held.append((login_user.user_id, lease_id, "exit"))

    monkeypatch.setattr(DepartmentFlowService, "hold_execution_lease", hold)
    ctx = DirectRunContext(conversation_id="c", run_id="r", tenant_id=TENANT, user_id=USER, execution_lease_id="L1")

    async with DirectRunner._default_department_slot(ctx):
        assert held == [(USER, "L1", "enter")]
    # Released when the run leaves the block.
    assert held[-1] == (USER, "L1", "exit")


async def test_workbench_system_prompt_prepares_the_saved_prompt(monkeypatch: pytest.MonkeyPatch):
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    saved = "当前时间：{cur_date}\n\n# 引用规则\n引用时逐字复制 <chunk_id> 中的来源 ID。\n\n# 语气\n礼貌。"

    async def config():
        return SimpleNamespace(systemPrompt=saved)

    monkeypatch.setattr(WorkStationService, "aget_config", staticmethod(config))

    prompt = await REAL_WORKBENCH_PROMPT()

    assert "{cur_date}" not in prompt and prompt.startswith("当前时间：20")
    # The legacy "copy the id verbatim" section became the handle rules.
    assert "<chunk_id>" not in prompt
    assert "# 语气" in prompt


@pytest.mark.parametrize("value", [None, "", "   "])
async def test_workbench_system_prompt_is_none_when_nothing_is_saved(monkeypatch: pytest.MonkeyPatch, value):
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    async def config():
        return SimpleNamespace(systemPrompt=value)

    monkeypatch.setattr(WorkStationService, "aget_config", staticmethod(config))

    assert await REAL_WORKBENCH_PROMPT() is None


async def test_daily_chat_telemetry_uses_the_legacy_events(monkeypatch: pytest.MonkeyPatch):
    from bisheng.workstation.domain.services import chat_service

    calls: list[tuple] = []

    async def log(user_id, conversation_id, start_time):
        calls.append((user_id, conversation_id, start_time))

    monkeypatch.setattr(chat_service, "log_telemetry_events", log)
    ctx = DirectRunContext(conversation_id="c", run_id="r", tenant_id=TENANT, user_id=USER)

    await REAL_TELEMETRY(ctx, 123.0)

    assert calls == [(str(USER), "c", 123.0)]
