"""Cursor encoding/decoding for cursor-based infinite-scroll list APIs (F027).

Schema (base64url-encoded JSON):
    {"v": 1, "s": "<context_signature>", "k": [<sort_key_value>, ..., <id>]}

- ``v``: schema version (currently 1); allows future format changes without breaking
  old cursors silently.
- ``s``: sort-context signature (e.g. ``"knowledge|sort_by=update_time"``); when a
  client reuses a cursor across a sort-order change, decode_cursor raises
  CursorDecodeError instead of silently scrolling to the wrong position.
- ``k``: ordered sort-key values; **last element must be a tie-breaker id** so the
  keyset comparison is strictly monotonic.

API layer is responsible for catching ``CursorDecodeError`` and translating it into
the module-specific ``*InvalidCursorError`` (see ``common/errcode/{knowledge,flow,
knowledge_space}.py``).
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Any, Optional, Sequence

CURSOR_SCHEMA_VERSION = 1


def _json_default(value: Any) -> Any:
    """JSON fallback for cursor values that ``json.dumps`` can't serialise natively.

    F027 sort keys frequently include ``datetime`` (``update_time``,
    ``create_time``); encode them as ISO 8601 strings so the cursor payload
    is valid JSON. SQLAlchemy ``DateTime`` columns compare against ISO
    string literals on both MySQL and DM via implicit cast, so the keyset
    WHERE on the decoded value still works.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f'cursor value type not JSON-serialisable: {type(value).__name__}')


class CursorDecodeError(ValueError):
    """Raised when a cursor cannot be decoded.

    Caught at the API layer and re-raised as a module-specific
    ``*InvalidCursorError`` so the frontend receives a stable business error code
    (10990 / 10550 / 18070) rather than a 500.
    """


def encode_cursor(sort_key: Sequence, *, context: str) -> str:
    """Encode a sort-key tuple plus context signature into a base64url cursor.

    Args:
        sort_key: Ordered sort-key values, last element must be a tie-breaker id.
        context: Sort-context signature, e.g. ``"knowledge|sort_by=update_time"``.

    Returns:
        URL-safe base64-encoded JSON string (no trailing ``=`` padding).
    """
    payload = {"v": CURSOR_SCHEMA_VERSION, "s": context, "k": list(sort_key)}
    raw = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False, default=_json_default,
    ).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(
    cursor: Optional[str],
    *,
    expected_key_len: int,
    expected_context: str,
) -> Optional[list]:
    """Decode a cursor string back into its sort-key list.

    Args:
        cursor: Cursor string from the request, or ``None``/``""`` for first page.
        expected_key_len: Number of elements expected in ``k`` (incl. id tie-breaker).
        expected_context: Context signature the caller expects; mismatch indicates
            the caller's sort/filter changed since this cursor was issued.

    Returns:
        The decoded sort-key list, or ``None`` if ``cursor`` is empty (first page).

    Raises:
        CursorDecodeError: When the cursor is malformed, version-incompatible,
            context-mismatched, or has wrong key length.
    """
    if not cursor:
        return None
    try:
        # Restore base64 padding that ``encode_cursor`` strips.
        pad = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except CursorDecodeError:
        raise
    except Exception as exc:
        raise CursorDecodeError(f"cursor decode failed: {exc}") from exc

    if payload.get("v") != CURSOR_SCHEMA_VERSION:
        raise CursorDecodeError(f"unsupported cursor version: {payload.get('v')}")
    if payload.get("s") != expected_context:
        raise CursorDecodeError(
            f"cursor context mismatch: got {payload.get('s')!r} expect {expected_context!r}"
        )
    key = payload.get("k")
    if not isinstance(key, list) or len(key) != expected_key_len:
        raise CursorDecodeError(
            f"cursor key length mismatch: got {len(key) if isinstance(key, list) else 'non-list'} expect {expected_key_len}"
        )
    return key
