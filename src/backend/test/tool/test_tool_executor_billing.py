"""Tests for ToolExecutor billing integration & real-time quota interception (AC-01, AC-11..AC-15, AC-22, AC-25, AC-28)."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.dsh import DshMonthlyTokenLimitExceededError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.tool.domain.services.executor import ToolExecutor


def _make_tool_stub(*, app_type=ApplicationTypeEnum.DAILY_CHAT, run_fn=None, arun_fn=None, user_id=42, tool_id=101):
    return SimpleNamespace(
        _require_current_use=AsyncMock(
            return_value=(SimpleNamespace(id=tool_id, type=10, tool_key="web_search"), SimpleNamespace(id=10, name="BuiltIn"))
        ),
        tool_id=tool_id,
        tool_key="web_search",
        tool_name="联网搜索",
        tool_group_id=10,
        tool_group_name="BuiltIn",
        tool_engine="bing",
        tool_is_preset=1,
        user_id=user_id,
        app_id="app-1",
        app_name="App",
        app_type=app_type,
        tool_instance=SimpleNamespace(
            _run=run_fn or Mock(return_value="sync-ok"),
            _arun=arun_fn or AsyncMock(return_value="async-ok"),
        ),
    )


@pytest.fixture
def patched_tool_env(monkeypatch):
    from bisheng.dsh.domain.services import tool_billing

    state = {
        "pricing": {"pricing_mode": "CREDITS", "currency": None, "price_micro": 2_000_000, "call_count": 1},
        "setting": CreditSettingState(currency="CNY", credit_value_micro=10_000, usd_cny_rate_micro=6_720_000),
        "check_calls": [],
        "recorded_events": [],
        "quota_reject": None,
        "ensure_enabled_err": None,
    }

    @contextmanager
    def _mock_scope():
        yield state

    def _read_config(session, *, tool_id: int):
        return state["pricing"], state["setting"]

    async def _check_quota(*, tenant_id, user_id, usage_month, monthly_token_limit=None, mode=""):
        state["check_calls"].append(
            {"tenant_id": tenant_id, "user_id": user_id, "usage_month": usage_month, "mode": mode}
        )
        if state["quota_reject"] and mode != "unmetered":
            raise QuotaRejected(state["quota_reject"])
        return (500, 1000)

    async def _record_usage(event):
        state["recorded_events"].append(event)
        return event

    quota_mock = SimpleNamespace(check_tool_quota=_check_quota, record_tool_usage=_record_usage)
    monkeypatch.setattr(tool_billing, "_session_scope", _mock_scope)
    monkeypatch.setattr(tool_billing, "_load_tool_pricing_and_setting", _read_config)
    monkeypatch.setattr(tool_billing, "_get_quota_store", AsyncMock(return_value=quota_mock))
    monkeypatch.setattr(tool_billing, "_read_user_monthly_limit", AsyncMock(return_value=10_000))

    avail = SimpleNamespace(
        ensure_enabled=AsyncMock(side_effect=lambda *a, **k: (_ for _ in ()).throw(state["ensure_enabled_err"]) if state["ensure_enabled_err"] else None),
        ensure_enabled_sync=Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(state["ensure_enabled_err"]) if state["ensure_enabled_err"] else None),
    )
    monkeypatch.setattr("bisheng.tool.domain.services.executor.UserToolAvailabilityService", lambda *a, **k: avail)

    token = current_tenant_id.set(2)
    try:
        yield state
    finally:
        current_tenant_id.reset(token)


async def test_free_tool_skips_quota_and_billing(patched_tool_env):
    patched_tool_env["pricing"] = {"pricing_mode": "MONEY", "currency": "CNY", "price_micro": 0, "call_count": 1}
    patched_tool_env["quota_reject"] = "quota_exceeded"
    tool = _make_tool_stub()

    res = await ToolExecutor._arun.__wrapped__(tool, config={})
    assert res == "async-ok"
    assert patched_tool_env["check_calls"] == []
    assert patched_tool_env["recorded_events"] == []


async def test_precheck_failure_never_checks_quota_or_bills(patched_tool_env):
    patched_tool_env["ensure_enabled_err"] = PermissionError("tool disabled")
    tool = _make_tool_stub()

    with pytest.raises(PermissionError, match="tool disabled"):
        await ToolExecutor._arun.__wrapped__(tool, config={})
    tool.tool_instance._arun.assert_not_awaited()
    assert patched_tool_env["check_calls"] == []
    assert patched_tool_env["recorded_events"] == []


async def test_non_task_paid_tool_blocks_on_quota_exhausted_and_charges_on_allowed(patched_tool_env):
    # Exhausted -> blocks with 26121 before execution
    patched_tool_env["quota_reject"] = "quota_exceeded"
    tool = _make_tool_stub(app_type=ApplicationTypeEnum.WORKFLOW)
    with pytest.raises(DshMonthlyTokenLimitExceededError):
        await ToolExecutor._arun.__wrapped__(tool, config={})
    tool.tool_instance._arun.assert_not_awaited()
    assert patched_tool_env["recorded_events"] == []

    # Allowed (used < limit, slight overdraft allowed) -> executes & bills
    patched_tool_env["quota_reject"] = None
    patched_tool_env["pricing"] = {"pricing_mode": "CREDITS", "currency": None, "price_micro": 2_000_000, "call_count": 1}
    # Simulate price changing during tool execution — must bill with frozen start snapshot (2 credits)!
    async def _run_and_mutate_price(*args, **kwargs):
        patched_tool_env["pricing"] = {"pricing_mode": "CREDITS", "currency": None, "price_micro": 9_000_000, "call_count": 1}
        return "workflow-ok"

    tool.tool_instance._arun = AsyncMock(side_effect=_run_and_mutate_price)
    res = await ToolExecutor._arun.__wrapped__(tool, config={})
    assert res == "workflow-ok"
    assert len(patched_tool_env["check_calls"]) == 2
    assert patched_tool_env["check_calls"][1]["mode"] == ""
    assert len(patched_tool_env["recorded_events"]) == 1
    ev = patched_tool_env["recorded_events"][0]
    assert ev.billed_tokens == 2_000_000
    assert ev.result == "success"
    assert ev.engine == "bing"


async def test_failures_timeouts_cancellations_and_linsight_soft_errors_record_true_result(patched_tool_env):
    # Linsight soft error must record result='failed' BEFORE converting to soft JSON (坑 2)
    linsight_tool = _make_tool_stub(
        app_type=ApplicationTypeEnum.LINSIGHT,
        arun_fn=AsyncMock(side_effect=RuntimeError("boom")),
    )
    out = await ToolExecutor._arun.__wrapped__(linsight_tool, config={})
    parsed = json.loads(out)
    assert parsed["状态"] == "失败"
    assert patched_tool_env["recorded_events"][-1].result == "failed"

    # Timeout in daily chat
    timeout_tool = _make_tool_stub(arun_fn=AsyncMock(side_effect=TimeoutError("timed out")))
    with pytest.raises(TimeoutError):
        await ToolExecutor._arun.__wrapped__(timeout_tool, config={})
    assert patched_tool_env["recorded_events"][-1].result == "timeout"

    # Cancellation in daily chat
    cancel_tool = _make_tool_stub(arun_fn=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await ToolExecutor._arun.__wrapped__(cancel_tool, config={})
    assert patched_tool_env["recorded_events"][-1].result == "cancelled"


async def test_task_mode_unmetered_bills_without_blocking_and_switch_off_bypasses(monkeypatch, patched_tool_env):
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.domain.services import chat_credits

    patched_tool_env["quota_reject"] = "quota_exceeded"
    tool = _make_tool_stub(app_type=ApplicationTypeEnum.LINSIGHT)

    # Inside task-mode unmetered lifecycle: runs & settles without blocking!
    with chat_credits.unmetered(), chat_credits.billing_context(source_type="linsight", source_id="task-7"):
        res = await ToolExecutor._arun.__wrapped__(tool, config={})
    assert res == "async-ok"
    assert patched_tool_env["check_calls"][0]["mode"] == "unmetered"
    assert patched_tool_env["recorded_events"][-1].source_type == "linsight"
    assert patched_tool_env["recorded_events"][-1].source_id == "task-7"

    # Open API unbilled skips billing completely
    patched_tool_env["check_calls"].clear()
    patched_tool_env["recorded_events"].clear()
    with chat_credits.billing_context(open_api_unbilled=True):
        await ToolExecutor._arun.__wrapped__(tool, config={})
    assert patched_tool_env["check_calls"] == []
    assert patched_tool_env["recorded_events"] == []

    # Global credit_billing switch disabled skips billing completely
    monkeypatch.setattr(settings.credit_billing, "enabled", False)
    await ToolExecutor._arun.__wrapped__(tool, config={})
    assert patched_tool_env["check_calls"] == []
    assert patched_tool_env["recorded_events"] == []


def test_sync_run_path_checks_quota_and_records_usage(patched_tool_env):
    tool = _make_tool_stub(app_type=ApplicationTypeEnum.WORKFLOW)
    res = ToolExecutor._run.__wrapped__(tool, config={})
    assert res == "sync-ok"
    assert len(patched_tool_env["check_calls"]) == 1
    assert len(patched_tool_env["recorded_events"]) == 1
    assert patched_tool_env["recorded_events"][0].result == "success"
