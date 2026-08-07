"""Attachment-parse failures must reach the chat bubble as a classified error.

Before this, a throttled OCR service surfaced as ``status_code: 500`` with the
provider's message buried in ``data.exception`` — the frontend showed "服务器错误"
and dropped the reason. These tests pin the contract the bubble reads: a
non-500 code, a stable ``error_type``, and the offending filename in ``detail``.
"""

import json

import pytest

from bisheng.common.errcode.workstation import ChatFileParseError
from bisheng.utils.exceptions import EtlException
from bisheng.workstation.domain.services import chat_service

# Verbatim shape of the PaddleOCR (Baidu AI Studio) throttle response.
OCR_THROTTLE_MESSAGE = (
    'PaddleOCR API error: status=429, resp={"logId":"5f23efd7","errorCode":12002,"errorMsg":"请求频率过高，请稍后重试"}'
)


async def _run_extract(monkeypatch, exc: Exception) -> ChatFileParseError:
    """Drive _extract_doc_text with a failing parser and return what it raised."""

    async def _boom(**_kwargs):
        raise exc

    monkeypatch.setattr(chat_service, "get_file_content", _boom)
    with pytest.raises(ChatFileParseError) as caught:
        await chat_service._extract_doc_text("/tmp/a.jpg", "invoice.jpg", 1)
    return caught.value


async def test_ocr_throttle_is_classified_as_transient(monkeypatch):
    err = await _run_extract(monkeypatch, EtlException(OCR_THROTTLE_MESSAGE))

    # Recovers on its own → the calm "busy, try again" card, not a hard failure.
    assert err.kwargs["error_type"] == "file_parse_busy"
    assert err.kwargs["filename"] == "invoice.jpg"
    assert err.kwargs["detail"].startswith("invoice.jpg: ")
    assert "请求频率过高" in err.kwargs["detail"]


async def test_unclassifiable_parse_failure_is_terminal(monkeypatch):
    err = await _run_extract(monkeypatch, EtlException("PaddleOCR API returned invalid JSON response"))

    assert err.kwargs["error_type"] == "file_parse_failed"


async def test_sse_envelope_carries_a_non_500_code_and_the_detail(monkeypatch):
    err = await _run_extract(monkeypatch, EtlException(OCR_THROTTLE_MESSAGE))

    raw = err.to_sse_event_instance_str()
    assert raw.startswith("event: error\n")
    payload = json.loads(raw.split("data: ", 1)[1])

    # The whole point: no longer the generic 500 the frontend translated away.
    assert payload["status_code"] == 12047
    assert payload["data"]["error_type"] == "file_parse_busy"
    assert "请求频率过高" in payload["data"]["detail"]


async def test_successful_extraction_passes_through(monkeypatch):
    async def _ok(**kwargs):
        return f"text of {kwargs['file_name']}"

    monkeypatch.setattr(chat_service, "get_file_content", _ok)
    assert await chat_service._extract_doc_text("/tmp/a.jpg", "invoice.jpg", 1) == "text of invoice.jpg"
