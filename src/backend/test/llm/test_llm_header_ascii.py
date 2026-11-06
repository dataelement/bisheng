"""HTTP header values passed to OpenAI-compatible clients must be ASCII."""

import pytest

from bisheng.llm.domain.llm.llm import _assert_ascii_http_header_values, _get_openai_params


def test_ascii_api_key_is_accepted():
    _assert_ascii_http_header_values({"api_key": "sk-ascii-token-123"})


def test_chinese_api_key_is_rejected():
    with pytest.raises(ValueError, match="api_key"):
        _assert_ascii_http_header_values({"api_key": "sk-中文密钥不能作为请求头"})


def test_chinese_default_header_is_rejected():
    with pytest.raises(ValueError, match="default_headers.X-Title"):
        _assert_ascii_http_header_values({"api_key": "sk-ok", "default_headers": {"X-Title": "毕昇灵思"}})


def test_openai_params_rejects_non_ascii_key():
    with pytest.raises(ValueError, match="api_key"):
        params = _get_openai_params(
            {},
            {"openai_api_key": "sk-中文密钥", "openai_api_base": "https://api.example.com"},
            {},
        )
        _assert_ascii_http_header_values(params)
