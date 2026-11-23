"""Bounded model-source page DTOs and unsigned, context-bound ordinals.

The context hash detects stale datasets/identities; it is not a signature or an
authorization grant. Every continuation must revalidate and authorize its page.
"""

import hashlib
import json
from dataclasses import dataclass

from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure


@dataclass(frozen=True, slots=True)
class ModelReferenceSourceEntry:
    disclosure: SourceDisclosure
    matched_slot_count: int


@dataclass(frozen=True, slots=True)
class ModelReferenceSourcePage:
    data: tuple[ModelReferenceSourceEntry, ...]
    page_size: int
    has_more: bool
    next_cursor: str | None


def validate_page_size(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 200:
        raise ResourceReferenceInvalidError(reason="model_reference_page_size_invalid")
    return value


def source_context(value) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ResourceReferenceInvalidError(reason="model_reference_cursor_context_invalid") from error
    return hashlib.sha256(raw.encode()).hexdigest()


def encode_source_cursor(ordinal: int, *, context: str) -> str:
    if type(ordinal) is not int or ordinal < 0:
        raise ResourceReferenceInvalidError(reason="model_reference_cursor_invalid")
    return encode_cursor([ordinal], context=context)


def decode_source_cursor(cursor: str, *, context: str, candidate_count: int) -> int:
    try:
        if type(cursor) is not str or not 1 <= len(cursor) <= 2048:
            raise ValueError("a bounded continuation is required")
        value = decode_cursor(cursor, expected_key_len=1, expected_context=context)
        ordinal = value[0]
        if type(ordinal) is not int or not 0 <= ordinal < candidate_count:
            raise ValueError("invalid source ordinal")
        if encode_source_cursor(ordinal, context=context) != cursor:
            raise ValueError("noncanonical source cursor")
        return ordinal
    except (CursorDecodeError, ValueError, TypeError, AttributeError, IndexError) as error:
        raise ResourceReferenceInvalidError(reason="model_reference_cursor_invalid") from error
