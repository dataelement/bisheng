from importlib.metadata import version

from mcp import types
from packaging.version import Version

from bisheng.common.services.config_service import settings
from bisheng.open_mcp.server import create_open_mcp_runtime


def test_pinned_sdk_supports_required_streamable_http_contract():
    sdk_version = Version(version("mcp"))
    runtime = create_open_mcp_runtime()

    assert Version("1.27.2") <= sdk_version < Version("2.0.0")
    assert runtime.manager.json_response is True
    assert runtime.manager.stateless is True
    assert runtime.manager.max_request_body_size == settings.open_mcp.max_request_body_bytes
    assert runtime.manager.security_settings.enable_dns_rebinding_protection is True
    assert runtime.manager.security_settings.allowed_hosts
    assert types.ListToolsRequest in runtime.manager.app.request_handlers
    assert types.CallToolRequest in runtime.manager.app.request_handlers
    assert "structuredContent" in types.CallToolResult.model_fields
