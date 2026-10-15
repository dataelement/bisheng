"""覆盖 AC: AC-03, AC-22, AC-26, AC-34."""

import json

import pytest
from pydantic import ValidationError

from bisheng.dsh.domain.schemas.contracts import DshEnabledConfig
from bisheng.dsh.domain.schemas.model_audit_context import AUDIT_FIELDS, parse_audit_context


@pytest.mark.parametrize("raw", [None, [], "", 1, True])
def test_invalid_object_drops_extension(raw):
    parsed = parse_audit_context(raw, AUDIT_FIELDS)
    assert parsed.conversation_id is None and parsed.request_kind is None


@pytest.mark.parametrize("value", ["A", "a", "你好", " ", "😀" * 256])
def test_exact_unicode_id_without_normalization(value):
    assert parse_audit_context({"conversation_id": value}, AUDIT_FIELDS).conversation_id == value


@pytest.mark.parametrize("value", ["", "😀" * 257, 1, False, [], None])
def test_bad_id_does_not_drop_kind(value):
    parsed = parse_audit_context({"conversation_id": value, "request_kind": "chat"}, AUDIT_FIELDS)
    assert parsed.conversation_id is None
    assert parsed.request_kind == "chat"
    assert parsed.invalid


@pytest.mark.parametrize("kind", ["chat", "compaction", "session-title"])
def test_known_kind_and_capability_subset(kind):
    raw = {"conversation_id": "case", "request_kind": kind, "user_id": "forged"}
    parsed = parse_audit_context(raw, ("conversation_id",))
    assert parsed.conversation_id == "case" and parsed.request_kind is None
    assert not hasattr(parsed, "user_id")


def test_invalid_kind_and_extension_size_boundaries():
    parsed = parse_audit_context({"conversation_id": "case", "request_kind": "UNKNOWN"}, AUDIT_FIELDS)
    assert parsed.conversation_id == "case" and parsed.request_kind is None
    prefix = {"conversation_id": "case", "padding": ""}
    overhead = len(json.dumps(prefix, ensure_ascii=False, separators=(",", ":")).encode("utf8"))
    prefix["padding"] = "x" * (4096 - overhead)
    assert parse_audit_context(prefix, AUDIT_FIELDS).conversation_id == "case"
    prefix["padding"] += "x"
    assert parse_audit_context(prefix, AUDIT_FIELDS).conversation_id is None
    assert parse_audit_context({"conversation_id": "\ud800"}, AUDIT_FIELDS).invalid


def test_capability_dto_optional_and_no_extra_version():
    dto = DshEnabledConfig(audit_context={"fields": list(AUDIT_FIELDS)})
    assert dto.contract_version == "0.5.0"
    assert DshEnabledConfig().audit_context is None
    with pytest.raises(ValidationError):
        DshEnabledConfig(audit_context={"fields": ["conversation_id"], "version": 1})
