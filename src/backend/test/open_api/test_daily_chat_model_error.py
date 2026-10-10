"""Daily chat answers an unavailable model with 26066 (F073 AC-13) and an unavailable tool with 26067."""

import pytest

from bisheng.common.errcode.open_api import OpenApiModelUnavailableError, OpenApiToolUnavailableError
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


def test_unavailable_tool_has_the_task_mode_code():
    # Same error as task mode: 26067 with the rejected tool in data.
    with pytest.raises(OpenApiToolUnavailableError) as exc_info:
        OpenDailyChatService._validate_model_and_tools(_req(tools=[{"id": 9, "tool_key": "x"}]), CONFIG)
    assert exc_info.value.code == 26067
    assert open_api_http_status(exc_info.value) == 400
    data = exc_info.value.to_dict()["data"]
    assert (data["tool_id"], data["tool_key"]) == (9, "x")


def test_available_model_and_tool_pass():
    OpenDailyChatService._validate_model_and_tools(_req(tools=[{"id": 30, "tool_key": "web"}]), CONFIG)
