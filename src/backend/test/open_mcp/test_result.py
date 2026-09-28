import json
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from bisheng.common.errcode.open_api import OpenApiScopeMissingError
from bisheng.open_mcp.contracts import KnowledgeResource, ResourceListData
from bisheng.open_mcp.result import error_result, error_result_from_exception, success_result
from bisheng.open_mcp.upload import McpUploadError


class _Payload(BaseModel):
    value: str


def _text_payload(result):
    return json.loads(result.content[0].text)


def test_success_result_keeps_text_and_structured_content_equivalent():
    result = success_result(_Payload(value="毕昇"))

    assert result.isError is False
    assert result.structuredContent == {"value": "毕昇"}
    assert _text_payload(result) == result.structuredContent


def test_success_result_adds_default_timezone_to_naive_business_datetime():
    result = success_result(
        ResourceListData(
            data=[
                KnowledgeResource(
                    id=67,
                    name="f067",
                    type=0,
                    auth_type="public",
                    is_released=False,
                    is_shared=False,
                    auto_tag_enabled=False,
                    create_time=datetime(2026, 9, 28, 10, 30),
                )
            ],
            page_size=1,
            has_more=False,
        )
    )

    assert result.structuredContent["data"][0]["create_time"] == "2026-09-28T10:30:00+08:00"
    assert _text_payload(result) == result.structuredContent


def test_success_result_preserves_existing_datetime_timezone():
    result = success_result(
        KnowledgeResource(
            id=67,
            name="f067",
            type=0,
            auth_type="public",
            is_released=False,
            is_shared=False,
            auto_tag_enabled=False,
            update_time=datetime(2026, 9, 28, 2, 30, tzinfo=UTC),
        )
    )

    assert result.structuredContent["update_time"] == "2026-09-28T02:30:00Z"


def test_error_result_has_machine_readable_code_without_structured_success_payload():
    result = error_result("INVALID_ARGUMENT", " invalid input ")

    assert result.isError is True
    assert result.structuredContent is None
    assert _text_payload(result) == {"error": {"code": "INVALID_ARGUMENT", "message": "invalid input"}}


def test_business_error_preserves_code_and_safe_message():
    result = error_result_from_exception(OpenApiScopeMissingError(required="knowledge:write"))

    assert _text_payload(result) == {"error": {"code": 26003, "message": "API credential lacks the required scope"}}


def test_http_error_maps_status_to_mcp_error_code():
    result = error_result_from_exception(HTTPException(status_code=404, detail={"message": "missing"}))

    assert _text_payload(result) == {"error": {"code": "NOT_FOUND", "message": "missing"}}


def test_validation_error_reports_field_without_pydantic_help_url():
    class _Arguments(BaseModel):
        count: int

    try:
        _Arguments.model_validate({"count": "not-an-int"})
    except ValidationError as exc:
        result = error_result_from_exception(exc)
    else:  # pragma: no cover - protects the test if Pydantic semantics change
        raise AssertionError("expected validation failure")

    payload = _text_payload(result)["error"]
    assert payload["code"] == "INVALID_ARGUMENT"
    assert payload["message"].startswith("count: ")
    assert "http" not in payload["message"]


def test_unexpected_error_does_not_leak_exception_details():
    result = error_result_from_exception(RuntimeError("database password secret"))

    assert _text_payload(result) == {"error": {"code": "TOOL_EXECUTION_FAILED", "message": "Tool execution failed"}}


def test_upload_error_keeps_stable_code_and_actionable_safe_message():
    result = error_result_from_exception(McpUploadError("Remote file exceeds the upload limit", code="FILE_TOO_LARGE"))

    assert _text_payload(result) == {
        "error": {
            "code": "FILE_TOO_LARGE",
            "message": "Remote file exceeds the upload limit",
        }
    }
