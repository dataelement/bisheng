"""Coverage AC: AC-27, AC-32, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-44, AC-48.

Exercise real repository/session boundaries. SQLite and injected uniqueness faults
verify rollback/retry contracts only; real MySQL/DM8 concurrency remains separate.
Native-writer promotion and receiver ACK/retry orchestration have separate tasks.
"""

import hashlib
import importlib
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.errcode.dsh import DshContentSafetyConflictError
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.repositories import content_safety
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key
from test.dsh.test_content_safety_repository import decoded, tenant_session, wire_hash


def projection_port():
    return importlib.import_module("bisheng.dsh.domain.repositories.content_safety_projection")


@pytest.fixture(autouse=True)
def metering_tables(content_safety_engine):
    DshModelCall.__table__.create(content_safety_engine, checkfirst=True)
    DshMonthlyUsage.__table__.create(content_safety_engine, checkfirst=True)


def output_event(factory, **changes):
    values = {
        "backend_request_id": str(uuid4()),
        "forwarded": True,
        "stage_results": {"input": "PASSED", "output": "BLOCKED"},
        "stage_versions": {"input": 1, "output": 1},
        "drain_status": "RUNNING",
    }
    values.update(changes)
    return factory(**values)


def append_and_merge(session, projection, raw):
    fact, duplicate = content_safety.append_event(session, decoded(raw), wire_hash(raw))
    audit = projection.merge_audit(session, decoded(raw))
    session.flush()
    return fact, audit, duplicate


def committed_merge(engine, projection, raw, tenant_id=101):
    with tenant_session(engine, tenant_id) as session, session.begin():
        fact, audit, duplicate = append_and_merge(session, projection, raw)
    return fact, audit, duplicate


def assert_external_unknowns(row):
    assert row.record_origin == "EXTERNAL_SAFETY"
    assert row.effective_mode is None
    assert row.model_result is None and row.response_result is None and row.usage_settlement is None
    assert row.model_started_at is None
    assert row.content_status == "NOT_CAPTURED" and row.audit_status == "NOT_APPLICABLE"
    assert row.model_name == ""
    assert row.model_name_digest == hashlib.sha256(b"").hexdigest()
    assert row.message_sources_ref is None


def test_input_blocked_creates_durable_external_without_model_or_usage_fact(
    content_safety_engine, content_safety_event
):
    projection = projection_port()
    raw = content_safety_event(session_id=None)
    fact, row, duplicate = committed_merge(content_safety_engine, projection, raw)
    assert not duplicate and isinstance(row, DshModelAuditRequest)
    assert row.request_id == raw["gateway_request_id"]
    assert row.started_at.replace(tzinfo=None) == datetime.fromisoformat(
        raw["request_started_at"].replace("Z", "+00:00")
    ).replace(tzinfo=None)
    assert_external_unknowns(row)
    assert row.model_entered is False and row.session_id is None
    assert row.has_sensitive_hit and row.input_sensitive_hit and not row.output_sensitive_hit
    assert row.content_safety_state == "BLOCKED"
    assert row.input_safety_state == "BLOCKED" and row.output_safety_state == "NOT_APPLICABLE"
    assert row.input_safety_version == 1 and row.output_safety_version == 1
    assert row.safety_source_id == raw["source_id"]
    assert row.safety_gateway_request_id == raw["gateway_request_id"]
    assert row.policy_version == raw["policy_version"] and row.builtin_digest == raw["builtin_digest"]
    assert row.content_safety_updated_at is not None and row.safety_projection_version > 0
    assert fact.audit_request_id == row.request_id and fact.association_status == "ASSOCIATED"
    with tenant_session(content_safety_engine) as session:
        stored = session.get(DshModelAuditRequest, row.request_id)
        assert stored.has_sensitive_hit and stored.model_entered is False
        receipt = content_safety.lookup_receipt(session, decoded(raw), wire_hash(raw))
        assert receipt.audit_request_id == row.request_id
        assert session.exec(select(DshModelCall)).all() == []
        assert session.exec(select(DshMonthlyUsage)).all() == []


def test_output_known_backend_id_creates_unknown_execution_external(content_safety_engine, content_safety_event):
    projection = projection_port()
    raw = output_event(content_safety_event)
    fact, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row.request_id == raw["backend_request_id"] != raw["gateway_request_id"]
    assert_external_unknowns(row)
    assert row.model_entered is None
    assert row.output_sensitive_hit and not row.input_sensitive_hit
    assert row.content_safety_state == "BLOCKED"
    assert fact.audit_request_id == row.request_id
    with tenant_session(content_safety_engine) as session:
        assert session.get(DshModelAuditRequest, raw["gateway_request_id"]) is None
        assert session.exec(select(DshModelCall)).all() == []
        assert session.exec(select(DshMonthlyUsage)).all() == []


@pytest.mark.parametrize("protocol", ["CHAT", "RESPONSES"])
def test_missing_backend_id_keeps_event_without_guessing_matching_native_row(
    content_safety_engine, content_safety_event, content_safety_native_audit, protocol
):
    projection = projection_port()
    native = content_safety_native_audit(conversation_id="synthetic-conversation")
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
    raw = output_event(content_safety_event, backend_request_id=None, protocol=protocol)
    fact, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row is None
    assert fact.audit_request_id is None and fact.association_status == "UNASSOCIATED"
    with tenant_session(content_safety_engine) as session:
        rows = session.exec(select(DshModelAuditRequest)).all()
        assert len(rows) == 1 and rows[0].request_id == native.request_id
        assert not rows[0].has_sensitive_hit
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


def test_nonforwarded_pass_does_not_manufacture_input_block_record(content_safety_engine, content_safety_event):
    projection = projection_port()
    raw = content_safety_event(stage_results={"input": "PASSED", "output": "NOT_APPLICABLE"}, hit_count=0, rule_refs=[])
    fact, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row is None and fact.audit_request_id is None
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshModelAuditRequest)).all() == []
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


@pytest.mark.parametrize("mode", ["METADATA", "CONTENT"])
def test_native_first_preserves_execution_delivery_settlement_and_marks_dirty(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_clock, mode
):
    projection = projection_port()
    native = content_safety_native_audit(
        effective_mode=mode,
        started_at=content_safety_clock.now() - timedelta(seconds=3),
        model_result="SUCCEEDED",
        response_result="COMPLETED",
        usage_settlement="SETTLED",
        audit_status="NORMAL",
        group_index_pending=False,
        conversation_id="native-conversation",
        conversation_key=conversation_key(101, 11, "native-conversation"),
        model_name_digest=hashlib.sha256(b"synthetic-model").hexdigest(),
    )
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
    raw = output_event(content_safety_event, backend_request_id=native.request_id)
    fact, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row.request_id == native.request_id and fact.audit_request_id == native.request_id
    assert row.record_origin == "MODEL" and row.model_entered is True
    assert row.effective_mode == mode and row.model_name == "synthetic-model"
    assert row.model_result == "SUCCEEDED" and row.response_result == "COMPLETED"
    assert row.usage_settlement == "SETTLED" and row.audit_status == "NORMAL"
    assert row.started_at.replace(tzinfo=None) == native.started_at.replace(tzinfo=None)
    assert row.model_started_at.replace(tzinfo=None) == native.model_started_at.replace(tzinfo=None)
    assert row.has_sensitive_hit and row.output_sensitive_hit
    assert row.conversation_id == "native-conversation"
    assert row.conversation_key == native.conversation_key
    assert row.group_index_pending and row.content_safety_updated_at is not None
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1


@pytest.mark.parametrize(
    "output_state,output_version,summary", [("UNREPORTED", 0, "UNREPORTED"), ("PASSED", 1, "PASSED")]
)
def test_native_summary_distinguishes_partial_snapshot_from_complete_pass(
    content_safety_engine,
    content_safety_event,
    content_safety_native_audit,
    output_state,
    output_version,
    summary,
):
    projection = projection_port()
    native = content_safety_native_audit(model_result="SUCCEEDED")
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
    raw = output_event(
        content_safety_event,
        backend_request_id=native.request_id,
        event_kind="FINAL",
        drain_status="NOT_REQUIRED",
        hit_count=0,
        rule_refs=[],
        stage_results={"input": "PASSED", "output": output_state},
        stage_versions={"input": 1, "output": output_version},
    )
    fact, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert fact.audit_request_id == native.request_id
    assert not row.has_sensitive_hit and not row.input_sensitive_hit and not row.output_sensitive_hit
    assert row.output_safety_state == output_state and row.output_safety_version == output_version
    assert row.content_safety_state == summary and row.model_result == "SUCCEEDED"


def test_safety_first_then_already_promoted_native_keeps_original_start_and_hit(
    content_safety_engine, content_safety_event, content_safety_clock
):
    projection = projection_port()
    raw = output_event(content_safety_event)
    _, external, _ = committed_merge(content_safety_engine, projection, raw)
    initial_start = external.started_at
    actual_start = content_safety_clock.now() + timedelta(seconds=2)
    # Native-writer promotion itself belongs to T025/T026, not this projection port.
    with tenant_session(content_safety_engine) as session, session.begin():
        promoted = session.get(DshModelAuditRequest, external.request_id)
        promoted.record_origin = "MODEL"
        promoted.effective_mode = "METADATA"
        promoted.model_entered = True
        promoted.model_started_at = actual_start
        promoted.model_name = "confirmed-model"
        promoted.model_name_digest = hashlib.sha256(b"confirmed-model").hexdigest()
        promoted.model_result = "SUCCEEDED"
        promoted.response_result = "COMPLETED"
        promoted.usage_settlement = "SETTLED"
        session.add(promoted)
    later = output_event(
        content_safety_event,
        gateway_request_id=raw["gateway_request_id"],
        backend_request_id=raw["backend_request_id"],
        event_version=2,
        event_kind="DRAIN",
        drain_status="FINISHED",
    )
    _, row, _ = committed_merge(content_safety_engine, projection, later)
    assert row.request_id == external.request_id and row.record_origin == "MODEL"
    assert row.started_at.replace(tzinfo=None) == initial_start.replace(tzinfo=None)
    assert row.model_started_at.replace(tzinfo=None) == actual_start.replace(tzinfo=None)
    assert row.model_name == "confirmed-model" and row.model_result == "SUCCEEDED"
    assert row.has_sensitive_hit and row.output_sensitive_hit
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 2


def test_repeated_snapshot_keeps_one_row_and_does_not_recount_projection(content_safety_engine, content_safety_event):
    projection = projection_port()
    raw = content_safety_event()
    first_fact, first, _ = committed_merge(content_safety_engine, projection, raw)
    projection_version = first.safety_projection_version
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(DshModelAuditRequest, first.request_id)
        row.group_indexed_sensitive_hit = True
        row.group_index_pending = False
        session.add(row)
    fact, row, duplicate = committed_merge(content_safety_engine, projection, raw)
    assert duplicate and fact.id == first_fact.id
    assert row.safety_projection_version == projection_version
    assert row.group_indexed_sensitive_hit and not row.group_index_pending
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1


@pytest.mark.parametrize("changed", [{"user_id": "22"}, {"model_id": "8"}])
def test_trusted_identity_change_is_stored_without_overwriting_original_owner(
    content_safety_engine, content_safety_event, content_safety_native_audit, changed
):
    projection = projection_port()
    native = content_safety_native_audit(model_result="SUCCEEDED")
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
    raw = output_event(content_safety_event, backend_request_id=native.request_id)
    _, first, _ = committed_merge(content_safety_engine, projection, raw)
    later = output_event(
        content_safety_event,
        gateway_request_id=raw["gateway_request_id"],
        backend_request_id=native.request_id,
        event_version=2,
        **changed,
    )
    fact, row, _ = committed_merge(content_safety_engine, projection, later)
    assert row is None and fact.audit_request_id is None
    assert fact.association_status == "UNASSOCIATED"
    with tenant_session(content_safety_engine) as session:
        original = session.get(DshModelAuditRequest, native.request_id)
        assert (original.tenant_id, original.user_id, original.model_id) == (101, 11, 7)
        assert original.has_sensitive_hit and original.model_result == "SUCCEEDED"
        assert original.safety_projection_version == first.safety_projection_version
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 2


def test_changed_tenant_is_retained_in_its_scope_without_reusing_old_gateway_association(
    content_safety_engine, content_safety_event, content_safety_identities
):
    projection = projection_port()
    raw = content_safety_event()
    _, first, _ = committed_merge(content_safety_engine, projection, raw)
    later = output_event(
        content_safety_event,
        identity=content_safety_identities[1],
        gateway_request_id=raw["gateway_request_id"],
        backend_request_id=None,
        event_version=2,
    )
    fact, row, _ = committed_merge(content_safety_engine, projection, later, tenant_id=202)
    assert row is None and fact.tenant_id == 202 and fact.user_id == 22
    assert fact.audit_request_id is None
    with tenant_session(content_safety_engine, 202) as session:
        assert session.exec(select(DshModelAuditRequest)).all() == []
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1
    with tenant_session(content_safety_engine) as session:
        assert session.get(DshModelAuditRequest, first.request_id).user_id == 11


@pytest.mark.parametrize("conversation", [None, {"conversation_id": ""}, {"request_kind": "chat"}])
def test_unusable_conversation_does_not_leave_external_row_permanently_dirty(
    content_safety_engine, content_safety_event, conversation
):
    projection = projection_port()
    raw = content_safety_event(conversation=conversation, session_id=None)
    fact, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row.has_sensitive_hit and fact.audit_request_id == row.request_id
    assert row.conversation_key is None and row.conversation_id is None
    assert row.session_id is None and not row.group_index_pending


def test_validated_hints_build_existing_conversation_key_without_invented_kind(
    content_safety_engine, content_safety_event
):
    projection = projection_port()
    raw = content_safety_event(conversation={"conversation_id": "safety-conversation"})
    _, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row.conversation_id == "safety-conversation"
    assert row.conversation_key == conversation_key(101, 11, "safety-conversation")
    assert row.request_kind is None and row.session_origin is None
    assert row.parent_conversation_id is None
    assert row.group_index_pending


def test_projection_requires_a_persisted_fact_and_never_creates_summary_alone(
    content_safety_engine, content_safety_event
):
    projection = projection_port()
    raw = content_safety_event()
    with tenant_session(content_safety_engine) as session:
        with pytest.raises(DshContentSafetyConflictError), session.begin():
            projection.merge_audit(session, decoded(raw))
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshModelAuditRequest)).all() == []
        assert session.exec(select(DshContentSafetyEvent)).all() == []


def test_caller_rollback_removes_fact_summary_and_dirty_together(content_safety_engine, content_safety_event):
    projection = projection_port()
    raw = content_safety_event()
    commits = []
    with tenant_session(content_safety_engine) as session:
        event.listen(session, "after_commit", lambda _: commits.append(True))
        with pytest.raises(RuntimeError, match="synthetic post-merge failure"), session.begin():
            fact, row, _ = append_and_merge(session, projection, raw)
            assert fact.audit_request_id == row.request_id and row.group_index_pending
            assert not commits
            raise RuntimeError("synthetic post-merge failure")
        assert not commits
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshContentSafetyEvent)).all() == []
        assert session.exec(select(DshModelAuditRequest)).all() == []


def test_failed_terminal_merge_rolls_back_new_event_and_leaves_old_summary(content_safety_engine, content_safety_event):
    projection = projection_port()
    raw = output_event(content_safety_event)
    _, first, _ = committed_merge(content_safety_engine, projection, raw)
    contradictory = output_event(
        content_safety_event,
        gateway_request_id=raw["gateway_request_id"],
        backend_request_id=raw["backend_request_id"],
        event_version=2,
        stage_results={"input": "PASSED", "output": "PASSED"},
        stage_versions={"input": 1, "output": 2},
        hit_count=0,
        rule_refs=[],
    )
    with tenant_session(content_safety_engine) as session:
        with pytest.raises(DshContentSafetyConflictError), session.begin():
            append_and_merge(session, projection, contradictory)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, first.request_id)
        assert row.output_safety_state == "BLOCKED" and row.output_sensitive_hit
        assert row.safety_projection_version == first.safety_projection_version
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


def test_unique_row_race_rolls_back_whole_transaction_then_fresh_retry_merges_winner(
    content_safety_engine, content_safety_event, content_safety_native_audit
):
    projection = projection_port()
    raw = output_event(content_safety_event)
    injections = []
    with tenant_session(content_safety_engine) as loser:

        def fail_external_insert(session, _flush_context, _instances):
            if any(isinstance(row, DshModelAuditRequest) for row in session.new):
                injections.append("audit unique collision")
                raise IntegrityError("synthetic audit unique collision", None, sqlite3.IntegrityError("UNIQUE"))

        event.listen(loser, "before_flush", fail_external_insert)
        try:
            with pytest.raises(IntegrityError), loser.begin():
                append_and_merge(loser, projection, raw)
        finally:
            event.remove(loser, "before_flush", fail_external_insert)
    assert injections == ["audit unique collision"]
    with tenant_session(content_safety_engine) as session, session.begin():
        assert session.exec(select(DshContentSafetyEvent)).all() == []
        assert session.exec(select(DshModelAuditRequest)).all() == []
        session.add(content_safety_native_audit(request_id=raw["backend_request_id"], model_result="SUCCEEDED"))
    fact, row, duplicate = committed_merge(content_safety_engine, projection, raw)
    assert not duplicate and fact.audit_request_id == raw["backend_request_id"]
    assert row.record_origin == "MODEL" and row.model_result == "SUCCEEDED" and row.output_sensitive_hit
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1


def test_output_hit_never_rewrites_existing_actual_usage_or_execution(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_clock
):
    projection = projection_port()
    native = content_safety_native_audit(model_result="SUCCEEDED", usage_settlement="SETTLED")
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
        session.add(
            DshModelCall(
                request_id=native.request_id,
                tenant_id=101,
                user_id=11,
                model_id=7,
                session_id=native.session_id,
                usage_month="2026-10",
                policy_version=1,
                event_version=3,
                quota_epoch=1,
                status="SUCCEEDED",
                usage_source="PROVIDER",
                input_tokens=12,
                output_tokens=8,
                total_tokens=20,
                started_at=content_safety_clock.now(),
            )
        )
        session.add(
            DshMonthlyUsage(
                tenant_id=101,
                user_id=11,
                model_id=7,
                usage_month="2026-10",
                billing_timezone="UTC",
                used_tokens=20,
                version=4,
            )
        )
    raw = output_event(content_safety_event, backend_request_id=native.request_id)
    _, row, _ = committed_merge(content_safety_engine, projection, raw)
    assert row.output_sensitive_hit and row.model_result == "SUCCEEDED" and row.usage_settlement == "SETTLED"
    with tenant_session(content_safety_engine) as session:
        call = session.get(DshModelCall, native.request_id)
        assert (call.status, call.input_tokens, call.output_tokens, call.total_tokens) == ("SUCCEEDED", 12, 8, 20)
        assert call.event_version == 3 and call.usage_source == "PROVIDER"
        usage = session.exec(select(DshMonthlyUsage)).one()
        assert usage.used_tokens == 20 and usage.version == 4
