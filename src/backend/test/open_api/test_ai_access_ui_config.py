"""Employee AI-access entries are a UI gate, not an API capability gate."""

from types import SimpleNamespace

import pytest

from bisheng.api.v1 import endpoints
from bisheng.core.config.open_platform import OpenApiConf


@pytest.mark.parametrize(
    "config, expected", [({}, False), ({"ai_access_ui_enabled": False}, False), ({"ai_access_ui_enabled": True}, True)]
)
def test_env_exposes_ai_access_ui_switch_without_disabling_api(monkeypatch, config, expected):
    open_api = OpenApiConf(**config)
    fake_settings = SimpleNamespace(
        environment="test",
        multi_tenant=SimpleNamespace(enabled=False),
        open_api=open_api,
        get_knowledge=lambda: SimpleNamespace(image_parser_enabled=False, version_management=None),
        get_from_db=lambda key: {"ai_access_ui_enabled": not expected} if key == "env" else "",
        get_system_login_method=lambda: SimpleNamespace(bisheng_pro=False, dashboard_pro=False),
        get_workflow_conf=lambda: SimpleNamespace(auto_rerun_on_open=False),
    )
    monkeypatch.setattr(endpoints, "bisheng_settings", fake_settings)

    response = endpoints.get_env()

    assert response.data["ai_access_ui_enabled"] is expected
    assert response.data["personal_token_enabled"] is True
    assert response.data["open_api_management_enabled"] is True
