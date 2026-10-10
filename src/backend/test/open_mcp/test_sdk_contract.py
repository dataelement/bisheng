from importlib.metadata import version
from types import SimpleNamespace

from mcp import types
from packaging.version import Version

from bisheng.common.services.config_service import settings
from bisheng.open_mcp import server as open_mcp_server
from bisheng.open_mcp.server import create_open_mcp_runtime


def test_pinned_sdk_supports_required_streamable_http_contract():
    sdk_version = Version(version("mcp"))
    runtime = create_open_mcp_runtime()

    assert Version("1.27.2") <= sdk_version < Version("2.0.0")
    assert runtime.manager.json_response is True
    assert runtime.manager.stateless is True
    assert runtime.manager.max_request_body_size == settings.open_mcp.max_request_body_bytes
    assert runtime.manager.security_settings.enable_dns_rebinding_protection is False
    assert runtime.manager.security_settings.allowed_hosts
    assert types.ListToolsRequest in runtime.manager.app.request_handlers
    assert types.CallToolRequest in runtime.manager.app.request_handlers
    assert "structuredContent" in types.CallToolResult.model_fields


def test_transport_security_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setattr(
        open_mcp_server,
        "settings",
        SimpleNamespace(
            open_mcp=SimpleNamespace(
                enable_dns_rebinding_protection=True,
                transport_allowed_hosts=["mcp.example.com"],
                transport_allowed_origins=["https://mcp.example.com"],
            ),
            open_api=SimpleNamespace(public_base_url=""),
        ),
    )

    security = open_mcp_server._transport_security_settings()

    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["mcp.example.com"]
    assert security.allowed_origins == ["https://mcp.example.com"]
