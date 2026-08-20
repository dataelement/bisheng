"""Detection logic of scripts/converge_media_no_asr_transcript.py — the ops
script that flips legacy "raw ASR JSON envelope stored as transcript" media
files from SUCCESS to FAILED(10956)."""

from __future__ import annotations

from scripts.converge_media_no_asr_transcript import (
    _extract_ingested_text,
    _is_garbage_transcript,
)

RAW_ENVELOPE = (
    '{"status_code": 200, "request_id": "890a6829d812451fba6703da8157bfc7", '
    '"code": "", "message": "", "output": null, "usage": null}'
)


def test_raw_envelope_is_garbage() -> None:
    assert _is_garbage_transcript(RAW_ENVELOPE)


def test_envelope_detected_regardless_of_key_order() -> None:
    reordered = (
        '{"request_id": "abc", "status_code": 200, "output": null, "usage": null}'
    )
    assert _is_garbage_transcript(reordered)


def test_empty_transcript_is_garbage() -> None:
    assert _is_garbage_transcript("")


def test_real_transcript_is_healthy() -> None:
    assert not _is_garbage_transcript("大家好，欢迎收听本期节目。")


def test_json_looking_speech_is_not_garbage() -> None:
    # A transcript that merely mentions JSON must not be converged.
    assert not _is_garbage_transcript('{"answer": "yes"}')
    assert not _is_garbage_transcript("status_code 200 的含义是请求成功")


def test_extract_ingested_text_reads_section() -> None:
    markdown = (
        "## 入库文本\n\n"
        f"{RAW_ENVELOPE}\n\n"
        "## 识别文本\n\n"
        f"{RAW_ENVELOPE}\n"
    )
    assert _extract_ingested_text(markdown) == RAW_ENVELOPE


def test_extract_ingested_text_falls_back_to_whole_document() -> None:
    assert _extract_ingested_text("plain transcript body") == "plain transcript body"
