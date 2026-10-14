import pytest
from pydantic import ValidationError

from bisheng.core.config.open_platform import OpenMcpConf


def test_open_mcp_safe_defaults_and_body_formula():
    config = OpenMcpConf()
    assert config.max_inline_upload_bytes == 50 * 1024 * 1024
    assert config.max_base64_characters == 4 * ((config.max_inline_upload_bytes + 2) // 3)
    assert config.max_request_body_bytes == config.max_base64_characters + 1024 * 1024
    assert config.enable_dns_rebinding_protection is False
    assert "localhost" in config.transport_allowed_hosts
    assert "localhost:*" in config.transport_allowed_hosts


def test_open_mcp_dns_rebinding_protection_can_be_enabled_explicitly():
    config = OpenMcpConf(enable_dns_rebinding_protection=True)
    assert config.enable_dns_rebinding_protection is True


@pytest.mark.parametrize("host", ["https://example.com", "example.com/path", "user@example.com", ""])
def test_allowed_hosts_reject_non_host_values(host):
    with pytest.raises(ValidationError):
        OpenMcpConf(file_url_allowed_hosts=[host])
