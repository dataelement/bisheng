"""覆盖 AC: AC-01, AC-07, AC-10, AC-11, AC-12。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from test.sso import test_kunlian_tenant_onboarding as onboarding_fixtures
from test.sso import test_kunlian_worker as fixtures

worker = fixtures.worker
directory_store = fixtures.directory_store
onboarding = onboarding_fixtures.onboarding
onboarding_store = onboarding_fixtures.onboarding_store


async def test_recovery_keeps_stage_cursor_and_durable_work_after_lost_delivery(worker):
    module, _, cfg, services, _, _, queued = worker
    cfg.auto_onboarding_enabled = True
    recovery = AsyncMock(
        return_value={"stage": "tenants", "has_more": True, "next_stage": "basic_access", "next_after_key": ""}
    )
    services.onboarding = SimpleNamespace(recover=recovery)
    queued.side_effect = OSError("mock lost notification")
    with tenant_execution_scope(7), pytest.raises(KunlianDependencyUnavailableError):
        await module.run_control_operation("recover", connection_id="fixture", after_key="external-a", stage="tenants")
    assert get_current_tenant_id() == 1
    queued.side_effect = None
    await module.run_control_operation("recover", connection_id="fixture", after_key="external-a", stage="tenants")
    assert queued.call_args.kwargs["args"] == ["fixture", "", "basic_access"]
    assert queued.call_args.kwargs["headers"] == {"tenant_id": 1}
    assert recovery.await_args.kwargs == {"stage": "tenants", "after_key": "external-a", "limit": 25}
    services.projection.project_pending.assert_not_awaited()


async def test_next_sweep_finds_work_inserted_before_previous_cursor(onboarding):
    from test.sso import test_kunlian_directory as directory

    s = onboarding
    await directory.publish(s.repo, tenants=[directory.tenant("z")], members=[directory.member(tid="z")])
    await s.service.recover("fixture", stage="tenants", after_key="m", limit=1)
    await directory.publish(
        s.repo,
        tenants=[directory.tenant("a"), directory.tenant("z")],
        members=[directory.member(tid="a"), directory.member("m2", "s2", "z")],
    )
    # 模拟 Worker 退出后新实例从 Beat 根游标开始, 不沿用旧扫描水位。
    other = type(s.service)(
        s.repo, s.config, tenants=s.tenants, users=s.users, roles=s.roles, access=s.access, projection=s.projection
    )
    await onboarding_fixtures.run_round(other)
    assert (await s.repo.get_tenant_binding("fixture", "a")).materialized


async def test_actual_runtime_wires_same_onboarding_into_login_session_and_worker(monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from bisheng.common.services import config_service
    from bisheng.sso_sync.application.runtime import KunlianRuntimeProvider
    from test.sso.test_kunlian_admission import config

    cfg = config()
    cfg.auto_onboarding_enabled = True
    cfg.login_scope_mode = "tenant_workspace_map"
    cfg.tenant_workspace_allowlist = {"A": ["WA"], "B": ["WB"]}
    cfg.allowed_tenant_id, cfg.allowed_workspace_ids = "", []
    cfg.endpoint_allowlist = [
        cfg.issuer + p for p in ("/.well-known/openid-configuration", "/oidc/jwks", "/oidc/introspect")
    ]
    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(
            sso_sync=SimpleNamespace(kunlian=cfg),
            multi_tenant=SimpleNamespace(enabled=True),
            aget_from_db=AsyncMock(return_value=True),
        ),
    )
    secrets = {
        getattr(cfg, name): "fixture-distinct-" + name
        for name in (
            "client_secret_reference",
            "sync_key_reference",
            "internal_secret_reference",
            "csrf_secret_reference",
        )
    }
    secrets[cfg.encryption_secret_reference] = Fernet.generate_key().decode()
    provider = KunlianRuntimeProvider(secret_resolver=lambda ref: SecretStr(secrets[ref]))
    try:
        services = await provider.worker_services()
        bindings = await provider.api_bindings()
        browser = await provider.browser_application()
        assert bindings.login.service.onboarding is services.onboarding
        assert browser.sessions.service.onboarding is services.onboarding
        assert services.onboarding.projection is services.projection
    finally:
        await provider.aclose()
