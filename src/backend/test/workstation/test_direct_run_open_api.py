"""F004 decision 14: what a direct run does for Open API daily chat, and the two
behaviours of the legacy daily chat that the direct run took over.

* Open API (AC-39): the run is unattended (no question to a user who is not
  there) and takes over the department lease the send request acquired.
* For every caller: the workbench custom system prompt leads the system prompt
  (design 决策 15), and a finished or failed run logs the daily-chat telemetry.

The REAL graph runs with the scripted model of ``test_direct_run``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from bisheng.workstation.domain.services import custom_system_prompt as custom_system_prompt_module
from bisheng.workstation.domain.services import direct_run
from bisheng.workstation.domain.services.direct_run import DirectRunContext, DirectRunner
from test.workstation.test_direct_run import ASK, TENANT, USER, make_env  # noqa: F401  (fixture)

# The root conftest replaces these two for every test; keep the real ones.
REAL_CUSTOM_PROMPT = custom_system_prompt_module.custom_system_prompt
REAL_TELEMETRY = direct_run.log_daily_chat_telemetry


def _system_text(model) -> str:
    first = model.inputs[0]
    return "\n".join(m.text for m in first if isinstance(m, SystemMessage))


class _Telemetry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, ctx: DirectRunContext, started_at: float) -> None:
        assert started_at > 0
        self.calls.append((ctx.run_id, ctx.conversation_id))


async def test_custom_prompt_leads_the_system_prompt(make_env):  # noqa: F811
    env = make_env([AIMessage(content="好的")])

    async def prompt() -> str:
        return "你是星河公司的智能助手。回答一律用表格。"

    runner = env.make_runner(custom_prompt=prompt)
    ctx = await env.submit("你好")

    assert (await env.run(ctx, runner)).status == "finished"

    system = _system_text(env.model)
    # The persona comes first; the main prompt no longer names an identity of its own.
    assert system.startswith("# 助手设定（由管理员配置）")
    assert system.index("回答一律用表格。") < system.index("本次是日常对话")
    assert "你是工作台助手" not in system
    assert "管理员设定的回答要求" not in system


async def test_no_custom_prompt_adds_no_section(make_env):  # noqa: F811
    env = make_env([AIMessage(content="好的")])
    ctx = await env.submit("你好")

    assert (await env.run(ctx)).status == "finished"

    assert "助手设定" not in _system_text(env.model)


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


async def test_custom_prompt_is_used_as_saved(monkeypatch: pytest.MonkeyPatch):
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    saved = "  你是星河助手。今天是 {cur_date}。  "

    async def config():
        return SimpleNamespace(customSystemPrompt=saved)

    monkeypatch.setattr(WorkStationService, "aget_config", staticmethod(config))

    # No date substitution: the time is in each turn's user message, and the prompt
    # prefix must stay the same across turns (design 决策 15).
    assert await REAL_CUSTOM_PROMPT() == "你是星河助手。今天是 {cur_date}。"


@pytest.mark.parametrize("value", [None, "", "   "])
async def test_empty_custom_prompt_uses_the_default_persona(monkeypatch: pytest.MonkeyPatch, value):
    from bisheng.brand.domain.schemas.brand_schema import BrandText
    from bisheng.brand.domain.services.brand_service import BrandService
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    async def config():
        return SimpleNamespace(customSystemPrompt=value)

    async def brand_name(self):
        return BrandText(zh="星河", en="Galaxy")

    monkeypatch.setattr(WorkStationService, "aget_config", staticmethod(config))
    monkeypatch.setattr(BrandService, "get_brand_name", brand_name)

    assert await REAL_CUSTOM_PROMPT() == "你是 星河 智能助手，帮助用户解答问题、完成工作任务。"


async def test_legacy_system_prompt_key_is_not_read(monkeypatch: pytest.MonkeyPatch):
    """Upgrade (design 决策 15): a saved ``systemPrompt`` no longer applies; the default does."""
    from bisheng.api.v1.schemas import WorkstationConfig
    from bisheng.brand.domain.services.brand_service import BrandService
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    config = WorkstationConfig.model_validate({"systemPrompt": "# 角色\n你是旧模板。当前时间：{cur_date}。"})
    assert config.customSystemPrompt is None
    assert "systemPrompt" not in config.model_dump()

    async def aget_config():
        return config

    async def no_brand(self):
        raise RuntimeError("brand row unreadable")

    monkeypatch.setattr(WorkStationService, "aget_config", staticmethod(aget_config))
    monkeypatch.setattr(BrandService, "get_brand_name", no_brand)

    assert await REAL_CUSTOM_PROMPT() == "你是 BISHENG 智能助手，帮助用户解答问题、完成工作任务。"


async def test_unreadable_config_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch):
    from bisheng.brand.domain.schemas.brand_schema import BrandText
    from bisheng.brand.domain.services.brand_service import BrandService
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    async def broken():
        raise RuntimeError("database down")

    async def brand_name(self):
        return BrandText(zh="BISHENG", en="BISHENG")

    monkeypatch.setattr(WorkStationService, "aget_config", staticmethod(broken))
    monkeypatch.setattr(BrandService, "get_brand_name", brand_name)

    assert (await REAL_CUSTOM_PROMPT()).startswith("你是 BISHENG 智能助手")


async def test_daily_chat_telemetry_uses_the_legacy_events(monkeypatch: pytest.MonkeyPatch):
    from bisheng.workstation.domain.services import chat_service

    calls: list[tuple] = []

    async def log(user_id, conversation_id, start_time):
        calls.append((user_id, conversation_id, start_time))

    monkeypatch.setattr(chat_service, "log_telemetry_events", log)
    ctx = DirectRunContext(conversation_id="c", run_id="r", tenant_id=TENANT, user_id=USER)

    await REAL_TELEMETRY(ctx, 123.0)

    assert calls == [(str(USER), "c", 123.0)]
