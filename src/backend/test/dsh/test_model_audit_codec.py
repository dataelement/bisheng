"""覆盖 AC: AC-04, AC-06, AC-07, AC-08, AC-10, AC-12, AC-14, AC-25, AC-26, AC-38."""

import json

from pydantic import BaseModel

from bisheng.dsh.domain.schemas.model_audit_events import ChannelExpectation
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope, encode_chunks


def test_model_encoding_is_shallow_incremental_and_preserves_required_nulls():
    class Message(BaseModel):
        content: str | None
        tool_calls: list[dict]

        def model_dump(self, **_kwargs):
            raise AssertionError("Audit encoding must not deep-copy the payload tree")

    message = Message(content=None, tool_calls=[{"index": index, "arguments": "x" * 100} for index in range(1000)])
    chunks = list(encode_chunks(message, 1024))
    assert max(map(len, chunks)) <= 1024
    decoded = json.loads(b"".join(chunks))
    assert decoded["content"] is None and decoded["tool_calls"] == message.tool_calls


def test_scope_discriminator_identity_case_and_encoding_isolation():
    scope = AuditScope(2, 20, "CONVERSATION", "X")
    assert scope.key != AuditScope(2, 20, "REQUEST", "X").key
    assert scope.key != AuditScope(2, 21, "CONVERSATION", "X").key
    assert scope.key != AuditScope(3, 20, "CONVERSATION", "X").key
    assert scope.key != AuditScope(2, 20, "CONVERSATION", "x").key
    assert scope.key != AuditScope(2, 20, "CONVERSATION", "X", 2).key


def test_incremental_unicode_structured_payload_is_complete_and_bounded():
    payload = {
        "role": "tool",
        "tool_call_id": "call",
        "content": [
            {"type": "text", "text": '你好\\\n"😀' * 10000},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,synthetic"}},
        ],
        "arguments": {"enabled": True, "value": None, "count": 12},
    }
    parts = list(encode_chunks(payload, 1024))
    assert len(parts) > 10 and all(0 < len(part) <= 1024 for part in parts)
    assert json.loads(b"".join(parts)) == payload
    assert list(encode_chunks(payload, 1024)) == parts


def test_expected_count_precedes_delivery_and_detects_missing_tail():
    expected = ChannelExpectation()
    sequence = expected.observe(b"first")
    assert sequence == 0 and expected.snapshot()["count"] == 1
    expected.observe(b"last")
    retained = ChannelExpectation()
    retained.observe(b"first")
    assert retained.snapshot() != expected.snapshot()
    assert ChannelExpectation().snapshot()["count"] == 0
