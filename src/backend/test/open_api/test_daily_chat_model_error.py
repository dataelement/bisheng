"""F073: daily chat answers an unavailable model with 26066, not a bare 400 (spec AC-13)."""

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.open_api import OpenApiModelUnavailableError
from bisheng.open_api.api.exception_handlers import open_api_http_status
from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.open_api.domain.services.daily_chat_service import OpenDailyChatService

CONFIG = {"models": [{"id": "7"}], "tools": [{"id": 3, "children": [{"id": 30, "tool_key": "web"}]}]}


def _req(**overrides):
    return OpenDailyChatCompletionReq.model_validate({"clientTimestamp": "t", "model": "7", **overrides})


def test_unavailable_model_has_a_platform_code():
    with pytest.raises(OpenApiModelUnavailableError) as exc_info:
        OpenDailyChatService._validate_model_and_tools(_req(model="8"), CONFIG)
    assert exc_info.value.code == 26066
    assert open_api_http_status(exc_info.value) == 400


def test_tool_error_is_unchanged():
    with pytest.raises(HTTPException) as exc_info:
        OpenDailyChatService._validate_model_and_tools(_req(tools=[{"id": 9, "tool_key": "x"}]), CONFIG)
    assert exc_info.value.status_code == 400


def test_available_model_and_tool_pass():
    OpenDailyChatService._validate_model_and_tools(_req(tools=[{"id": 30, "tool_key": "web"}]), CONFIG)
