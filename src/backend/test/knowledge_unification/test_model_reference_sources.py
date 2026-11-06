"""T867/T869: opaque source ordinals and real model-impact source disclosure."""

import base64
import json
from dataclasses import asdict

import pytest

from bisheng.common.cursor import encode_cursor
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.domain.services.model_reference_cursor import (
    ModelReferenceSourceEntry,
    ModelReferenceSourcePage,
    decode_source_cursor,
    encode_source_cursor,
    source_context,
    validate_page_size,
)
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure


def test_source_cursor_contains_only_ordinal_and_context_digest_not_names_or_keys():
    context = source_context({"identity": {"credential": "private-key"}, "command": [1, [11]], "digest": "a" * 64})
    cursor = encode_source_cursor(7, context=context)
    decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert decoded == {"v": 1, "s": context, "k": [7]}
    assert len(context) == 64 and "private" not in json.dumps(decoded)
    assert decode_source_cursor(cursor, context=context, candidate_count=8) == 7
    assert source_context({"b": [1], "a": True}) == source_context({"a": True, "b": [1]})


@pytest.mark.parametrize("ordinal", [-1, True, 1.0, "1", None, 9])
def test_source_cursor_rejects_invalid_or_out_of_range_ordinals(ordinal):
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(encode_cursor([ordinal], context="ctx"), context="ctx", candidate_count=9)


@pytest.mark.parametrize("cursor", [None, "", False, "not-base64", "A" * 2049])
def test_source_cursor_requires_a_bounded_canonical_continuation(cursor):
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(cursor, context="ctx", candidate_count=9)


def test_source_cursor_rejects_wrong_context_and_noncanonical_payload():
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(encode_source_cursor(1, context="old"), context="new", candidate_count=9)
    raw = json.dumps({"v": 1, "s": "ctx", "k": [1], "extra": "hidden"}).encode()
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(ResourceReferenceInvalidError):
        decode_source_cursor(cursor, context="ctx", candidate_count=9)
    with pytest.raises(ResourceReferenceInvalidError):
        source_context({"value": float("nan")})


@pytest.mark.parametrize("size", [True, False, 0, -1, 201, 1.0, "50", None])
def test_source_page_size_does_not_coerce_invalid_input(size):
    with pytest.raises(ResourceReferenceInvalidError):
        validate_page_size(size)


def test_bounded_page_preserves_nullable_disclosure_and_actual_slot_count():
    item = ModelReferenceSourceEntry(SourceDisclosure(SourceKey(101, "assistant", "7", "current"), "name", None, None), 3)
    page = ModelReferenceSourcePage((item,), 1, True, "opaque")
    assert asdict(page)["data"][0]["matched_slot_count"] == 3
    assert item.disclosure.entry is None and item.disclosure.version_label is None
    assert validate_page_size(200) == 200
