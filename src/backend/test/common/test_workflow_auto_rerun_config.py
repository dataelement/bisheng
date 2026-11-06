from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bisheng.api.v1 import endpoints
from bisheng.common.services.config_service import ConfigService
from bisheng.core.config.settings import WorkflowConf


def test_workflow_auto_rerun_defaults_to_disabled():
    assert WorkflowConf().auto_rerun_on_open is False


@pytest.mark.parametrize("value", [True, False])
def test_workflow_auto_rerun_accepts_explicit_booleans(value):
    assert WorkflowConf(auto_rerun_on_open=value).auto_rerun_on_open is value


@pytest.mark.parametrize("value", [None, 1, 0, "true", "false", [], {}])
def test_workflow_auto_rerun_invalid_values_fail_closed(value):
    assert WorkflowConf(auto_rerun_on_open=value).auto_rerun_on_open is False


def test_initdb_config_ships_disabled_workflow_auto_rerun():
    config_path = Path(__file__).parents[2] / "bisheng" / "initdb_config.yaml"
    config = yaml.safe_load(config_path.read_text())

    assert config["workflow"]["auto_rerun_on_open"] is False


def test_existing_config_gets_missing_switch_without_overwriting_values():
    file_config = """\
workflow:
  # Auto rerun an already-ended standalone workflow conversation when opened.
  auto_rerun_on_open: false
  timeout: 5
"""
    db_config = """\
workflow:
  timeout: 30
"""

    merged, added = ConfigService.merge_missing_config(file_config, db_config)
    config = yaml.safe_load(merged)

    assert config["workflow"] == {"timeout": 30, "auto_rerun_on_open": False}
    assert added == ["workflow.auto_rerun_on_open"]


def test_env_exposes_only_normalized_workflow_auto_rerun_switch(monkeypatch):
    fake_settings = SimpleNamespace(
        environment="test",
        multi_tenant=SimpleNamespace(enabled=False),
        get_knowledge=lambda: SimpleNamespace(image_parser_enabled=False, version_management=None),
        get_from_db=lambda key: {} if key == "env" else "",
        get_system_login_method=lambda: SimpleNamespace(bisheng_pro=False, dashboard_pro=False),
        # F049 / F054 switches ``get_env`` reads on this branch; the fake settings
        # object has to carry them or the endpoint raises before reaching workflow.
        open_platform=SimpleNamespace(enabled=False),
        app_runtime=SimpleNamespace(enabled=False),
        get_workflow_conf=lambda: WorkflowConf(auto_rerun_on_open=True),
    )
    monkeypatch.setattr(endpoints, "bisheng_settings", fake_settings)

    response = endpoints.get_env()

    assert response.data["workflow"] == {"auto_rerun_on_open": True}


def test_env_fails_closed_when_workflow_config_cannot_be_loaded(monkeypatch):
    def raise_invalid_config():
        raise TypeError("workflow config is invalid")

    fake_settings = SimpleNamespace(
        environment="test",
        multi_tenant=SimpleNamespace(enabled=False),
        get_knowledge=lambda: SimpleNamespace(image_parser_enabled=False, version_management=None),
        get_from_db=lambda key: {} if key == "env" else "",
        get_system_login_method=lambda: SimpleNamespace(bisheng_pro=False, dashboard_pro=False),
        # F049 / F054 switches ``get_env`` reads on this branch; the fake settings
        # object has to carry them or the endpoint raises before reaching workflow.
        open_platform=SimpleNamespace(enabled=False),
        app_runtime=SimpleNamespace(enabled=False),
        get_workflow_conf=raise_invalid_config,
    )
    monkeypatch.setattr(endpoints, "bisheng_settings", fake_settings)

    response = endpoints.get_env()

    assert response.data["workflow"] == {"auto_rerun_on_open": False}
