from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from bisheng.api.v1 import endpoints
from bisheng.common.errcode.server import SystemConfigInvalidError
from bisheng.common.services.config_service import ConfigService
from bisheng.core.config.sso_sync import (
    KunlianConf,
    apply_kunlian_db_overrides,
    validate_sso_sync_db_config,
)
from bisheng.sso_sync.application.runtime import KunlianRuntimeProvider
from test.sso import test_kunlian_worker as worker_fixtures


def test_apply_kunlian_db_overrides_respects_precedence_and_strict_booleans():
    assert KunlianConf().auto_onboarding_enabled is True
    base_enabled = KunlianConf(auto_onboarding_enabled=True)
    base_disabled = KunlianConf(auto_onboarding_enabled=False)

    assert apply_kunlian_db_overrides(base_enabled, None).auto_onboarding_enabled is True
    assert apply_kunlian_db_overrides(base_enabled, {}).auto_onboarding_enabled is True
    assert apply_kunlian_db_overrides(base_enabled, {"kunlian": {"auto_onboarding_enabled": None}}).auto_onboarding_enabled is True
    assert apply_kunlian_db_overrides(base_enabled, {"kunlian": {"auto_onboarding_enabled": "false"}}).auto_onboarding_enabled is True
    assert apply_kunlian_db_overrides(base_enabled, {"kunlian": {"auto_onboarding_enabled": 0}}).auto_onboarding_enabled is True
    assert apply_kunlian_db_overrides(base_enabled, {"kunlian": {"auto_onboarding_enabled": False}}).auto_onboarding_enabled is False
    assert base_enabled.auto_onboarding_enabled is True

    assert apply_kunlian_db_overrides(base_disabled, {"kunlian": {"auto_onboarding_enabled": None}}).auto_onboarding_enabled is False
    assert apply_kunlian_db_overrides(base_disabled, {"kunlian": {"auto_onboarding_enabled": True}}).auto_onboarding_enabled is True


def test_initdb_config_ships_null_kunlian_auto_onboarding_and_backfills_preserving_comments():
    config_path = Path(__file__).parents[2] / "bisheng" / "initdb_config.yaml"
    file_text = config_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(file_text)
    assert parsed["sso_sync"]["kunlian"]["auto_onboarding_enabled"] is None

    legacy_db_yaml = """\
environment:
  enable_register: false
"""
    merged, added = ConfigService.merge_missing_config(file_text, legacy_db_yaml)
    assert "sso_sync" in added
    merged_parsed = yaml.safe_load(merged)
    assert merged_parsed["environment"]["enable_register"] is False
    assert merged_parsed["sso_sync"]["kunlian"]["auto_onboarding_enabled"] is None
    assert "无需重启" in merged


async def test_runtime_provider_skips_db_read_when_kunlian_disabled(monkeypatch):
    aget_from_db = AsyncMock()
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings",
        SimpleNamespace(
            sso_sync=SimpleNamespace(kunlian=KunlianConf(login_enabled=False, directory_enabled=False)),
            multi_tenant=SimpleNamespace(enabled=False),
            aget_from_db=aget_from_db,
        ),
    )

    provider = KunlianRuntimeProvider(secret_resolver=lambda _ref: None)
    await provider._load()
    aget_from_db.assert_not_awaited()


async def test_runtime_provider_hot_reloads_auto_onboarding_from_db(monkeypatch):
    db_values = {"sso_sync": None}

    async def fake_aget_from_db(key):
        return db_values.get(key)

    base_conf = worker_fixtures.config()
    base_conf.auto_onboarding_enabled = True
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings",
        SimpleNamespace(
            sso_sync=SimpleNamespace(kunlian=base_conf),
            multi_tenant=SimpleNamespace(enabled=True),
            aget_from_db=AsyncMock(side_effect=fake_aget_from_db),
        ),
    )

    provider = KunlianRuntimeProvider(secret_resolver=lambda _ref: None)

    services = await provider.worker_services()
    assert services.config.auto_onboarding_enabled is True
    assert services.onboarding.config.auto_onboarding_enabled is True

    db_values["sso_sync"] = {"kunlian": {"auto_onboarding_enabled": False}}
    services = await provider.worker_services()
    assert services.config.auto_onboarding_enabled is False
    assert services.onboarding.config.auto_onboarding_enabled is False

    db_values["sso_sync"] = {"kunlian": {"auto_onboarding_enabled": True}}
    services = await provider.worker_services()
    assert services.config.auto_onboarding_enabled is True
    assert services.onboarding.config.auto_onboarding_enabled is True

    # Test doubles that return a scalar bool for any key must not break loading.
    db_values["sso_sync"] = True
    services = await provider.worker_services()
    assert services.config.auto_onboarding_enabled is True


@pytest.mark.parametrize("bad_value", ["true", "false", 1, 0, []])
def test_validate_sso_sync_db_config_rejects_non_bool_auto_onboarding(bad_value):
    with pytest.raises(ValueError):
        validate_sso_sync_db_config({"kunlian": {"auto_onboarding_enabled": bad_value}})


def test_save_config_rejects_invalid_sso_sync_and_allows_null_or_bool(monkeypatch):
    stored = SimpleNamespace(value="")
    deleted_keys = []

    monkeypatch.setattr(endpoints.ConfigDao, "get_config", lambda _key: stored)
    monkeypatch.setattr(endpoints.ConfigDao, "insert_config", lambda obj: setattr(stored, "value", obj.value))
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: SimpleNamespace(delete=deleted_keys.append))

    with pytest.raises(SystemConfigInvalidError):
        endpoints.save_config(
            {"data": "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: 'true'\n"},
            admin_user=SimpleNamespace(user_id=1),
        )

    resp = endpoints.save_config(
        {"data": "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: false\n"},
        admin_user=SimpleNamespace(user_id=1),
    )
    assert resp.status_code == 200
    assert "config:initdb_config" in deleted_keys

    resp_null = endpoints.save_config(
        {"data": "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: null\n"},
        admin_user=SimpleNamespace(user_id=1),
    )
    assert resp_null.status_code == 200


def test_env_exposes_kunlian_auto_onboarding_effective_and_default_flags(monkeypatch):
    base_conf = KunlianConf(directory_enabled=True, auto_onboarding_enabled=True)
    override_conf = KunlianConf(directory_enabled=True, auto_onboarding_enabled=False)
    fake_settings = SimpleNamespace(
        environment="test",
        multi_tenant=SimpleNamespace(enabled=True),
        open_platform=SimpleNamespace(enabled=False),
        app_runtime=SimpleNamespace(enabled=False),
        open_api=SimpleNamespace(pat_enabled=False, management_ui_enabled=False),
        sso_sync=SimpleNamespace(kunlian=base_conf),
        get_kunlian_conf=lambda: override_conf,
        get_knowledge=lambda: SimpleNamespace(image_parser_enabled=False, version_management=None),
        get_workflow_conf=lambda: SimpleNamespace(
            auto_rerun_on_open=False,
            code_node_enabled=False,
            platform_agent=SimpleNamespace(mode="off", policy_revision="v1", resource_base_url=""),
            platform_knowledge=SimpleNamespace(
                mode="off",
                policy_revision="v1",
                connection_id="",
                resource_base_url="",
            ),
            platform_llm=SimpleNamespace(enabled=False, resource_base_url=""),
        ),
        get_from_db=lambda key: {} if key == "env" else "",
        get_system_login_method=lambda: SimpleNamespace(bisheng_pro=False, dashboard_pro=False),
    )
    monkeypatch.setattr(endpoints, "bisheng_settings", fake_settings)

    payload = endpoints.get_env().model_dump() if hasattr(endpoints.get_env(), "model_dump") else endpoints.get_env()
    data = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    assert data["kunlian_sso_configured"] is True
    assert data["kunlian_auto_onboarding_default"] is True
    assert data["kunlian_auto_onboarding_enabled"] is False
