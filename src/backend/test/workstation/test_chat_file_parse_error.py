"""Attachment-parse failures must reach the chat bubble as a classified error.

Before this, a throttled OCR service surfaced as ``status_code: 500`` with the
provider's message buried in ``data.exception`` — the frontend showed "服务器错误"
and dropped the reason. These tests pin the contract the bubble reads: a
non-500 code, a stable ``error_type``, and the offending filename in ``detail``.
"""

import json

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeMediaNoRecognizableAudioError,
    KnowledgeMediaTranscriptionError,
)
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


async def test_media_without_speech_is_narrated_not_raised(monkeypatch):
    """A silent clip must not cost the user the question they wrote with it.

    ASR returning nothing is not a fault: the user attached a file, they did not
    ask for a transcript. The turn continues and the model is told the file
    carried no speech — rather than the whole message failing, or the attachment
    vanishing so the model answers as if nothing were sent.
    """

    class _Pipeline:
        def __init__(self, **_kwargs):
            pass

        async def arun(self):
            raise KnowledgeMediaNoRecognizableAudioError()

    monkeypatch.setattr(
        "bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline",
        _Pipeline,
    )
    # The suite stubs knowledge_imp; give it back the one call this path makes.
    monkeypatch.setattr(
        chat_service.knowledge_imp.KnowledgeUtils,
        "chunk2promt",
        classmethod(lambda _cls, chunk, metadata: f"[file name]:{metadata['source']}\n{chunk}"),
        raising=False,
    )

    content = await chat_service.get_file_content(
        filepath_local="/tmp/clip.avi",
        file_name="clip.avi",
        invoke_user_id=1,
    )

    assert chat_service.NO_SPEECH_PLACEHOLDER in content
    # Still wrapped as an attachment, so the model sees which file was empty.
    assert "clip.avi" in content


async def test_transcription_service_failure_still_raises(monkeypatch):
    """A broken ASR service is a real fault — narrating it would hide the outage."""

    class _Pipeline:
        def __init__(self, **_kwargs):
            pass

        async def arun(self):
            raise KnowledgeMediaTranscriptionError()

    monkeypatch.setattr(
        "bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline",
        _Pipeline,
    )

    with pytest.raises(KnowledgeMediaTranscriptionError):
        await chat_service.get_file_content(
            filepath_local="/tmp/clip.avi",
            file_name="clip.avi",
            invoke_user_id=1,
        )
