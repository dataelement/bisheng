"""覆盖 AC: AC-40, AC-41, AC-42, AC-43, AC-44, AC-46, AC-47."""

import sqlalchemy as sa

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.schemas.model_audit_context import parse_audit_context


def test_child_compaction_and_sources_are_independent():
    context = parse_audit_context(
        {
            "conversation_id": "child",
            "request_kind": "compaction",
            "session_origin": "subagent",
            "parent_conversation_id": "parent",
            "message_sources": {
                "items": [{"message_index": 0, "sources": [{"kind": "skill-catalog", "form": "catalog"}]}],
                "truncated": False,
            },
        },
        message_count=1,
    )
    assert context.session_origin == "subagent"
    assert context.parent_conversation_id == "parent"
    assert context.message_sources["items"][0]["sources"][0]["kind"] == "skill-catalog"
    assert "skill-catalog" not in repr(context)


def test_malformed_sources_cannot_drop_valid_identity():
    context = parse_audit_context({"conversation_id": "child", "request_kind": "chat", "message_sources": "x" * 20000})
    assert context.conversation_id == "child" and context.request_kind == "chat"
    assert context.message_sources_status == "INVALID"
    assert parse_audit_context({"conversation_id": "ok", "unknown": "x" * 100000}).conversation_id == "ok"


def test_duplicate_out_of_range_and_boolean_indices_are_not_trusted():
    items = [{"message_index": i, "sources": [{"kind": "user"}]} for i in [0, 0, 1, True, -1, 9]]
    context = parse_audit_context({"message_sources": {"items": items, "truncated": False}}, message_count=2)
    assert context.message_sources["items"] == [{"message_index": 1, "sources": [{"kind": "user"}]}]
    assert context.message_sources_status == "PARTIAL"


def test_parent_requires_valid_subagent_and_capability():
    raw = {"conversation_id": "a", "session_origin": "main", "parent_conversation_id": "b"}
    assert parse_audit_context(raw).parent_conversation_id is None
    raw["session_origin"] = "subagent"
    raw["parent_conversation_id"] = "a"
    assert parse_audit_context(raw).parent_conversation_id is None
    assert parse_audit_context(raw, ("conversation_id",)).session_origin is None


def test_annotation_budget_keeps_identity_and_marks_partial():
    items = [{"message_index": i, "sources": [{"kind": "k" * 64 + str(j)} for j in range(4)]} for i in range(129)]
    # Valid 64-character identifiers, enough to exceed the byte budget before 128 entries.
    for item in items:
        item["sources"] = [{"kind": "k" * 63 + str(j)} for j in range(4)]
    context = parse_audit_context(
        {"conversation_id": "ok", "message_sources": {"items": items, "truncated": False}}, message_count=200
    )
    assert context.conversation_id == "ok"
    assert context.message_sources_status == "PARTIAL"
    assert len(context.message_sources["items"]) < 128


def test_provenance_fields_and_indexes_are_present_at_table_creation():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            DshModelAuditRequest.__table__.create(connection)
            columns = {column["name"] for column in sa.inspect(connection).get_columns("dsh_model_audit_request")}
            assert {
                "session_origin",
                "parent_conversation_id",
                "message_sources_status",
                "message_sources_ref",
            } <= columns
            assert "ix_dma_request_sources" in {
                index["name"] for index in sa.inspect(connection).get_indexes("dsh_model_audit_request")
            }
    finally:
        engine.dispose()
