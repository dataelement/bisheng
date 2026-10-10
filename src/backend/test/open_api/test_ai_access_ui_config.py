"""Employee AI-access entries are a UI gate, not an API capability gate."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bisheng.api.v1 import endpoints
from bisheng.common.services.config_service import ConfigService
from bisheng.core.config.open_platform import OpenApiConf


@pytest.mark.parametrize(
    "config, expected", [({}, False), ({"ai_access_ui_enabled": False}, False), ({"ai_access_ui_enabled": True}, True)]
)
def test_env_exposes_ai_access_ui_switch_without_disabling_api(monkeypatch, config, expected):
    # Deliberately disagree with DB config: the server YAML must not control UI.
    open_api = SimpleNamespace(pat_enabled=True, management_ui_enabled=True, ai_access_ui_enabled=not expected)
    monkeypatch.setattr(ConfigService, "get_from_db", lambda self, key: config if key == "open_api" else {})
    service = ConfigService()
    fake_settings = SimpleNamespace(
        environment="test",
        multi_tenant=SimpleNamespace(enabled=False),
        open_api=open_api,
        get_knowledge=lambda: SimpleNamespace(image_parser_enabled=False, version_management=None),
        get_from_db=lambda key: {"ai_access_ui_enabled": not expected} if key == "env" else "",
        get_system_login_method=lambda: SimpleNamespace(bisheng_pro=False, dashboard_pro=False),
        get_workflow_conf=lambda: SimpleNamespace(auto_rerun_on_open=False),
        get_ai_access_ui_enabled=lambda: service.get_ai_access_ui_enabled(),
    )
    monkeypatch.setattr(endpoints, "bisheng_settings", fake_settings)

    response = endpoints.get_env()

    assert response.data["ai_access_ui_enabled"] is expected
    assert response.data["personal_token_enabled"] is True
    assert response.data["open_api_management_enabled"] is True


@pytest.mark.parametrize(
    "block",
    [
        None,
        [],
        "invalid",
        {},
        {"ai_access_ui_enabled": "false"},
        {"ai_access_ui_enabled": "true"},
        {"ai_access_ui_enabled": 1},
    ],
)
def test_missing_or_invalid_system_config_hides_entries(monkeypatch, block):
    monkeypatch.setattr(ConfigService, "get_from_db", lambda self, key: block)

    assert ConfigService().get_ai_access_ui_enabled() is False


def test_system_config_changes_apply_without_recreating_settings(monkeypatch):
    state = {"ai_access_ui_enabled": False}
    monkeypatch.setattr(ConfigService, "get_from_db", lambda self, key: state)
    service = ConfigService()

    assert service.get_ai_access_ui_enabled() is False
    state["ai_access_ui_enabled"] = True
    assert service.get_ai_access_ui_enabled() is True
    state["ai_access_ui_enabled"] = False
    assert service.get_ai_access_ui_enabled() is False
    assert service.open_api.pat_enabled == OpenApiConf().pat_enabled
    assert service.open_api.management_ui_enabled == OpenApiConf().management_ui_enabled


def test_system_config_template_hides_entries_by_default():
    config_path = Path(__file__).parents[2] / "bisheng" / "initdb_config.yaml"
    data = yaml.safe_load(config_path.read_text())

    assert data["open_api"]["ai_access_ui_enabled"] is False


def test_existing_system_config_gets_switch_without_overwriting_values():
    template = "open_api:\n  ai_access_ui_enabled: false\n"
    existing = "open_api:\n  custom_setting: preserved\n"
    merged, added = ConfigService.merge_missing_config(template, existing)

    assert yaml.safe_load(merged)["open_api"] == {"custom_setting": "preserved", "ai_access_ui_enabled": False}
    assert added == ["open_api.ai_access_ui_enabled"]

    enabled = "open_api:\n  ai_access_ui_enabled: true\n"
    merged, added = ConfigService.merge_missing_config(template, enabled)
    assert yaml.safe_load(merged)["open_api"]["ai_access_ui_enabled"] is True
    assert added == []
