"""Public-only entry behavior and credential-free business errors."""

import importlib
import json
from pathlib import Path

import pytest

from bisheng.core.config.settings import Settings
from bisheng_langchain.utils.egress_policy import DestinationDenied
from bisheng_langchain.utils.safe_http_errors import RequestFailed, RequestTimeout, ResponseTooLarge


def service_module():
    return importlib.import_module("bisheng.tool.domain.services.egress")


def test_no_private_exception_configuration_exists():
    assert "tool_egress" not in Settings.model_fields
    assert not hasattr(service_module(), "get_tool_egress_policy")


@pytest.mark.parametrize(
    "error_type,code",
    [(DestinationDenied, 15033), (RequestFailed, 15034), (ResponseTooLarge, 15035), (RequestTimeout, 15036)],
)
def test_safe_errors_map_to_stable_business_codes_without_exception_details(error_type, code):
    error = error_type()
    error.args = ("https://user:secret@internal/path?token=secret",)
    mapped = service_module().map_tool_egress_error(error)
    assert mapped.code == code
    assert mapped.exception is None
    assert "secret" not in mapped.to_json_str()
    assert "internal" not in mapped.to_json_str()


def test_unknown_error_is_not_laundered_into_safe_business_error():
    error = RuntimeError("unexpected")
    assert service_module().map_tool_egress_error(error) is error


def test_business_errors_have_all_three_source_translations():
    root = Path(__file__).resolve().parents[3]
    for language in ("en", "ja", "zh-Hans"):
        translations = json.loads((root / "frontend/packages/locales/src/api_errors" / f"{language}.json").read_text())
        for code in range(15033, 15037):
            assert translations.get(str(code)), f"Missing {language} translation for {code}"
