"""T004 — Cursor encoding/decoding unit tests (AC-07, AC-08)."""
from __future__ import annotations

import base64
import json

import pytest

from bisheng.common.cursor import (
    CURSOR_SCHEMA_VERSION,
    CursorDecodeError,
    decode_cursor,
    encode_cursor,
)


# ---------------------------------------------------------------------------
# AC-07: encode_cursor produces the documented schema
# ---------------------------------------------------------------------------


def test_encode_emits_v_s_k_schema():
    cursor = encode_cursor(("2026-05-28T12:34:56", 42), context="knowledge|sort_by=update_time")
    # Restore padding to decode.
    pad = "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(cursor + pad))
    assert payload == {
        "v": CURSOR_SCHEMA_VERSION,
        "s": "knowledge|sort_by=update_time",
        "k": ["2026-05-28T12:34:56", 42],
    }


def test_encode_handles_three_element_key():
    """Knowledge-space children use a 3-element sort key (ext_rank, file_name, id)."""
    cursor = encode_cursor((1, "report.pdf", 9876), context="space_children|order=ext_rank_asc,file_name_asc")
    pad = "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(cursor + pad))
    assert payload["k"] == [1, "report.pdf", 9876]


def test_encode_handles_unicode_in_key():
    """Sort keys can contain unicode (e.g., Chinese file names)."""
    cursor = encode_cursor((1, "报告.pdf", 42), context="space_children|order=ext_rank_asc,file_name_asc")
    decoded = decode_cursor(
        cursor,
        expected_key_len=3,
        expected_context="space_children|order=ext_rank_asc,file_name_asc",
    )
    assert decoded == [1, "报告.pdf", 42]


# ---------------------------------------------------------------------------
# AC-07: encode/decode roundtrip preserves data
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip_two_element_key():
    ctx = "knowledge|sort_by=update_time"
    cursor = encode_cursor(("2026-05-28T12:34:56", 42), context=ctx)
    decoded = decode_cursor(cursor, expected_key_len=2, expected_context=ctx)
    assert decoded == ["2026-05-28T12:34:56", 42]


def test_encode_decode_roundtrip_three_element_key():
    ctx = "space_children|order=ext_rank_asc,file_name_asc"
    cursor = encode_cursor((1, "report.pdf", 9876), context=ctx)
    decoded = decode_cursor(cursor, expected_key_len=3, expected_context=ctx)
    assert decoded == [1, "report.pdf", 9876]


# ---------------------------------------------------------------------------
# AC-08: empty cursor means first page (not an error)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty", [None, ""])
def test_decode_returns_none_on_empty_cursor(empty):
    decoded = decode_cursor(
        empty,
        expected_key_len=2,
        expected_context="knowledge|sort_by=update_time",
    )
    assert decoded is None


# ---------------------------------------------------------------------------
# AC-08: malformed cursor raises CursorDecodeError
# ---------------------------------------------------------------------------


def test_decode_raises_on_invalid_base64():
    with pytest.raises(CursorDecodeError, match="cursor decode failed"):
        decode_cursor(
            "not!valid!base64!@#$",
            expected_key_len=2,
            expected_context="knowledge|sort_by=update_time",
        )


def test_decode_raises_on_invalid_json():
    # Valid base64 of non-JSON content.
    cursor = base64.urlsafe_b64encode(b"this is not JSON").rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError, match="cursor decode failed"):
        decode_cursor(
            cursor,
            expected_key_len=2,
            expected_context="knowledge|sort_by=update_time",
        )


def test_decode_raises_on_unsupported_v():
    payload = {"v": 999, "s": "knowledge|sort_by=update_time", "k": ["x", 1]}
    raw = json.dumps(payload).encode()
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError, match="unsupported cursor version"):
        decode_cursor(
            cursor,
            expected_key_len=2,
            expected_context="knowledge|sort_by=update_time",
        )


def test_decode_raises_on_context_mismatch():
    """AD-02 sort-context signature defense: prevent cross-sort-by cursor reuse."""
    cursor = encode_cursor(("2026-05-28", 42), context="knowledge|sort_by=update_time")
    with pytest.raises(CursorDecodeError, match="cursor context mismatch"):
        decode_cursor(
            cursor,
            expected_key_len=2,
            expected_context="knowledge|sort_by=create_time",  # different sort_by
        )


def test_decode_raises_on_key_length_mismatch():
    cursor = encode_cursor(("2026-05-28", 42), context="knowledge|sort_by=update_time")
    with pytest.raises(CursorDecodeError, match="cursor key length mismatch"):
        decode_cursor(
            cursor,
            expected_key_len=3,  # caller expects 3, cursor has 2
            expected_context="knowledge|sort_by=update_time",
        )


def test_decode_raises_when_k_is_missing():
    payload = {"v": 1, "s": "knowledge|sort_by=update_time"}  # no k
    raw = json.dumps(payload).encode()
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError, match="cursor key length mismatch"):
        decode_cursor(
            cursor,
            expected_key_len=2,
            expected_context="knowledge|sort_by=update_time",
        )


def test_decode_raises_when_k_is_not_a_list():
    payload = {"v": 1, "s": "knowledge|sort_by=update_time", "k": "not a list"}
    raw = json.dumps(payload).encode()
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError, match="cursor key length mismatch"):
        decode_cursor(
            cursor,
            expected_key_len=2,
            expected_context="knowledge|sort_by=update_time",
        )


# ---------------------------------------------------------------------------
# Cursor format hygiene: no trailing padding, URL-safe
# ---------------------------------------------------------------------------


def test_encoded_cursor_has_no_padding():
    cursor = encode_cursor(("2026-05-28T12:34:56", 42), context="knowledge|sort_by=update_time")
    assert "=" not in cursor


def test_encoded_cursor_is_url_safe():
    """Should not contain ``+`` or ``/`` characters (base64url alphabet)."""
    cursor = encode_cursor(("a" * 100, 999_999), context="knowledge|sort_by=update_time")
    assert "+" not in cursor and "/" not in cursor
