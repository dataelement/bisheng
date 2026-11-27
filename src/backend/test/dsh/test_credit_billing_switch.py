"""Tests for global credit_billing.enabled switch & decoupling from desktop DSH access (AC-27..AC-30)."""

import importlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.services.access import DshPrincipal


def test_credit_billing_defaults_to_enabled_and_supports_disable(monkeypatch):
    from bisheng.core.config.settings import Settings

    default_settings = Settings()
    assert default_settings.credit_billing.enabled is True

    disabled_settings = Settings(credit_billing={"enabled": False})
    assert disabled_settings.credit_billing.enabled is False

    monkeypatch.setenv("BS_CREDIT_BILLING__ENABLED", "false")
    env_settings = Settings()
    assert env_settings.credit_billing.enabled is False


def test_legacy_dsh_and_bs_client_enabled_keys_are_ignored_smoothly():
    from bisheng.core.config.dsh import DshSettings
    from bisheng.core.config.settings import Settings

    assert "enabled" not in DshSettings.model_fields
    loaded_legacy_dsh = Settings(dsh={"enabled": False, "billing_timezone": "UTC"})
    assert loaded_legacy_dsh.bs_client.billing_timezone == "UTC"
    assert loaded_legacy_dsh.credit_billing.enabled is True

    loaded_legacy_client = Settings(bs_client={"enabled": False, "billing_timezone": "Asia/Shanghai"})
    assert loaded_legacy_client.bs_client.billing_timezone == "Asia/Shanghai"
    assert loaded_legacy_client.credit_billing.enabled is True


@pytest.mark.parametrize("billing_enabled", [True, False])
async def test_browser_config_exposes_credit_billing_switch_while_desktop_stays_enabled(monkeypatch, billing_enabled):
    from bisheng.admin.application import request_admission
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.api.dependencies import get_settings
    from bisheng.dsh.api.endpoints.settings import settings_service
    from bisheng.dsh.api.router import router
    from bisheng.dsh.config import DshSettings
    from bisheng.dsh.domain.schemas.settings import DshManagementSettings

    monkeypatch.setattr(settings.credit_billing, "enabled", billing_enabled)
    service = AsyncMock()
    service.read.return_value = DshManagementSettings(
        enabled=True, download_url="https://desktop.example/download", launch_url="bisheng://login"
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: DshSettings(platform_public_url="http://test")
    app.dependency_overrides[settings_service] = lambda: service
    request_admission.install_request_admission(app)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dsh/browser-config")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["management_enabled"] is True
        assert data["credit_billing_enabled"] is billing_enabled


def test_chat_credits_governed_respects_credit_billing_switch(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.domain.services import chat_credits

    monkeypatch.setattr(settings.credit_billing, "enabled", True)
    assert chat_credits.governed(SimpleNamespace(app_type="daily_chat")) is True

    monkeypatch.setattr(settings.credit_billing, "enabled", False)
    assert chat_credits.governed(SimpleNamespace(app_type="daily_chat")) is False


@pytest.mark.parametrize("billing_enabled", [False, True])
async def test_workbench_models_keep_visibility_independent_of_billing(monkeypatch, billing_enabled):
    from bisheng.common.services.config_service import settings
    from bisheng.dsh import runtime
    from bisheng.dsh.domain.services import model_catalog

    authorized = AsyncMock(return_value=[{"id": "1", "name": "auth-only"}])
    visible = AsyncMock(return_value=[{"id": "2", "name": "visible-only"}])
    monkeypatch.setattr(runtime, "read_policy", authorized)
    monkeypatch.setattr(model_catalog, "visible_workbench_models", visible)

    monkeypatch.setattr(settings.credit_billing, "enabled", billing_enabled)
    result = await model_catalog.user_workbench_models(7, config={})
    assert result == [{"id": "2", "name": "visible-only"}]
    visible.assert_awaited_once_with(7, {})
    authorized.assert_not_awaited()


async def test_desktop_models_and_completions_bypass_quota_and_keep_visibility_when_billing_off(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.domain.services.model import DshModelService

    monkeypatch.setattr(settings.credit_billing, "enabled", False)

    model = SimpleNamespace(
        id=10, model_name="qwen", config={"pricing": {"input": "2", "output": "6", "currency": "CNY"}}, create_time=None
    )
    server = SimpleNamespace(name="provider", type="openai")
    usage = AsyncMock()
    execution = SimpleNamespace(
        invoke=AsyncMock(return_value={"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}),
        usage=DshTokenUsage(input_tokens=5, output_tokens=3, total_tokens=8),
        provider_request_id="req-1",
        status="SUCCEEDED",
    )

    class _Adapter:
        def prepare(self, *args, **kwargs):
            return execution

    policy_reader = AsyncMock()
    visible_models_reader = AsyncMock(return_value=[10])
    service = DshModelService(
        policy_reader=policy_reader,
        visible_models_reader=visible_models_reader,
        model_loader=AsyncMock(return_value=(model, server)),
        llm_builder=lambda *args: SimpleNamespace(),
        capabilities_for=lambda *args: ChatCapabilities(),
        usage=usage,
        now=lambda: datetime(2026, 11, 25, tzinfo=UTC),
        hint_context_reader=AsyncMock(return_value=object()),
    )
    service.adapter = _Adapter()

    principal = DshPrincipal(tenant_id="1", user_id="42", session_id="s1")
    models_resp = await service.list_models(principal)
    assert [m["id"] for m in models_resp["data"]] == ["bisheng:10"]
    assert "pricing_hint" not in models_resp["data"][0]
    visible_models_reader.assert_awaited_once_with(42)
    policy_reader.assert_not_awaited()

    request = DshChatRequest(model="bisheng:10", messages=[{"role": "user", "content": "hello"}])
    completion = await service.complete(principal, request)
    assert completion["choices"][0]["message"]["content"] == "hi"
    usage.check_and_start.assert_not_awaited()
    usage.record_usage.assert_not_awaited()


async def test_credits_endpoint_returns_unlimited_unbilled_when_billing_off(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.api.endpoints.unified_policy import month_credits

    monkeypatch.setattr(settings.credit_billing, "enabled", False)
    runtime = SimpleNamespace(settings=SimpleNamespace(billing_timezone="Asia/Shanghai"))
    data = await month_credits(runtime, tenant_id=1, user_id=20)
    assert data["unlimited"] is True
    assert data["billing_enabled"] is False
    assert data["used"] == "0"


def test_worker_beat_keeps_dsh_projection_and_recovery_when_billing_off(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.worker import config as worker_config

    monkeypatch.setattr(settings.credit_billing, "enabled", False)
    reloaded = importlib.reload(worker_config)
    try:
        assert "dsh-usage-projection" in reloaded.beat_schedule
        assert "dsh-usage-inspection" in reloaded.beat_schedule
        assert "dsh-operation-recovery" in reloaded.beat_schedule
    finally:
        monkeypatch.setattr(settings.credit_billing, "enabled", True)
        importlib.reload(worker_config)


async def test_direct_runner_default_admit_uses_credit_billing_switch(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.domain.services import chat_credits
    from bisheng.linsight.domain.services import agent_factory
    from bisheng.workstation.domain.services.direct_run import DirectRunContext, DirectRunner

    runner = object.__new__(DirectRunner)
    ctx = DirectRunContext(conversation_id="c1", run_id="r1", tenant_id=1, user_id=2, model_id=10)
    fake_model = SimpleNamespace(id=10)
    resolve_mock = AsyncMock(return_value=(fake_model, None))
    admit_mock = AsyncMock()
    monkeypatch.setattr(agent_factory, "_resolve_model", resolve_mock)
    monkeypatch.setattr(chat_credits, "admit_round", admit_mock)

    monkeypatch.setattr(settings.credit_billing, "enabled", False)
    await runner._default_admit(ctx)
    resolve_mock.assert_not_awaited()
    admit_mock.assert_not_awaited()

    monkeypatch.setattr(settings.credit_billing, "enabled", True)
    await runner._default_admit(ctx)
    resolve_mock.assert_awaited_once()
    admit_mock.assert_awaited_once_with(fake_model)
