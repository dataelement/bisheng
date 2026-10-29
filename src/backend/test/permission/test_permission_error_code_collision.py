"""Permission errors and information-source errors must remain distinguishable."""

import inspect
import json
from pathlib import Path

import pytest

from bisheng.common.errcode import channel, permission
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.permission.api.responses import permission_error_response


def _codes(module):
    return {
        cls.Code
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, BaseErrorCode) and cls.__module__ == module.__name__
    }


def test_permission_codes_never_overlap_channel_codes():
    assert _codes(permission).isdisjoint(_codes(channel))
    assert permission.PermissionDeniedError.Code == 19000
    assert channel.InformationSourceParseError.Code == 19003
    assert permission.PermissionFGAUnavailableError is permission.PermissionServiceUnavailableError


@pytest.mark.parametrize("code", range(25020, 25027))
def test_permission_error_codes_have_copy_in_both_clients_and_all_languages(code):
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    for lang, platform_lang in (("zh-Hans", "zh-Hans"), ("en", "en-US"), ("ja", "ja")):
        source = json.loads((frontend / f"packages/locales/src/api_errors/{lang}.json").read_text())
        platform = json.loads((frontend / f"platform/public/locales/{platform_lang}/api_errors.json").read_text())
        client = json.loads((frontend / f"client/src/locales/{lang}/api_errors.gen.json").read_text())
        assert source[str(code)] == platform[str(code)] == client[str(code)]
        assert source[str(code)] != source["19003"]


def test_invalid_resource_response_cannot_be_mistaken_for_parse_failure():
    result = permission_error_response(permission.PermissionInvalidResourceError())
    assert result.status_code == 25022
    assert result.status_message == "Invalid resource type or ID"
