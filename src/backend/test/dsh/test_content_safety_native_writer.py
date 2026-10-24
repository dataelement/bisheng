"""Coverage AC: AC-03, AC-32, AC-38, AC-41, AC-47, AC-49, AC-52.

Use the real capture, writer, repository and encrypted storage with isolated SQL
and the existing synthetic object port. SQLite does not prove dual-DB behavior.
"""

from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_content import DshModelAuditContent, DshModelAuditOccurrence
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditManifest, DshModelAuditRequest
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.repositories import content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter
from bisheng.dsh.infrastructure.model_audit_body_buffer import AuditBodyBuffer
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope, conversation_key
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage, StoredAuditBlock
from test.dsh.model_audit_fixtures import AUDIT_MODELS, ControlledAuditQueue, FaultAuditObjects
from test.dsh.test_content_safety_merge import committed_merge, output_event
from test.dsh.test_content_safety_repository import tenant_session

SAFETY_FIELDS = (
    "safety_source_id",
    "safety_gateway_request_id",
    "input_safety_state",
    "output_safety_state",
    "input_safety_version",
    "output_safety_version",
    "input_sensitive_hit",
    "output_sensitive_hit",
    "has_sensitive_hit",
    "content_safety_state",
    "content_safety_updated_at",
    "policy_version",
    "builtin_digest",
    "safety_projection_version",
    "group_indexed_sensitive_hit",
)
KEY_ID = "synthetic-native-writer-key"
KEY = bytes(range(32))


@pytest.fixture
def native_environment(content_safety_engine, content_safety_faults):
    models = (*AUDIT_MODELS, DshModelCall, DshMonthlyUsage)
    SQLModel.metadata.create_all(content_safety_engine, tables=[model.__table__ for model in models])
    tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in models)
    objects = FaultAuditObjects()
    storage = EncryptedAuditStorage(objects, AuditKeyRing({KEY_ID: KEY}, active_id=KEY_ID), max_block_bytes=64)

    @contextmanager
    def repository_scope():
        with strict_tenant_filter(), Session(content_safety_engine, expire_on_commit=False) as session:
            with session.begin():
                yield DshModelAuditWriteRepository(session)
                session.flush()
                content_safety_faults.check("native_before_commit")

    return DshModelAuditWriter(repository_scope, lambda: storage, attempts=1), storage, objects


def safety_first(engine, factory, **changes):
    values = {
        "session_id": None,
        "conversation": None,
        "event_version": 3,
        "stage_versions": {"input": 1, "output": 3},
        "policy_version": 17,
        "builtin_digest": "b" * 64,
    }
    values.update(changes)
    raw = output_event(factory, **values)
    _, row, _ = committed_merge(engine, content_safety_projection, raw)
    return raw, row


def capture_events(raw, clock, *, mode="CONTENT", **changes):
    started_at = clock.now() + timedelta(seconds=2)
    data = {
        "request_id": raw["backend_request_id"],
        "tenant_id": int(raw["tenant_id"]),
        "user_id": int(raw["user_id"]),
        "model_id": int(raw["model_id"]),
        "session_id": "10100000-0000-4000-8000-000000000099",
        "model_name": "confirmed-native-model",
        "provider_name": "synthetic-provider",
        "conversation_id": "confirmed-native-conversation",
        "request_kind": "chat",
        "session_origin": "main",
        "parent_conversation_id": None,
        "effective_mode": mode,
        "started_at": started_at,
        "input_units": 1,
    }
    data.update(changes)
    queue = ControlledAuditQueue()
    capture = AuditCapture(
        data,
        queue,
        now=lambda: started_at + timedelta(seconds=1),
        chunk_bytes=64,
        request_budget_bytes=65536,
        digest_key=KEY,
        key_version=KEY_ID,
    )
    capture.entered([{"role": "user", "content": "synthetic confidential input"}])
    capture.output({"content": "synthetic model answer"})
    capture.terminal("SUCCEEDED")
    capture.response("COMPLETED")
    capture.usage("SETTLED")
    return queue.drain()


def snapshot(row):
    return {name: getattr(row, name) for name in SAFETY_FIELDS}


def assert_promoted(row, external, metadata, mode):
    assert row.record_origin == "MODEL" and row.effective_mode == mode and row.model_entered is True
    assert row.started_at.replace(tzinfo=None) == external.started_at.replace(tzinfo=None)
    assert row.model_started_at.replace(tzinfo=None) == metadata["started_at"].replace(tzinfo=None)
    assert row.session_id == metadata["session_id"]
    assert row.model_name == metadata["model_name"]
    assert row.model_name_digest == sha256(metadata["model_name"].encode()).hexdigest()
    assert row.provider_name == metadata["provider_name"]
    assert row.conversation_id == metadata["conversation_id"]
    assert row.conversation_key == conversation_key(row.tenant_id, row.user_id, metadata["conversation_id"])
    assert row.request_kind == metadata["request_kind"] and row.session_origin == metadata["session_origin"]
    assert row.parent_conversation_id == metadata["parent_conversation_id"]
    assert snapshot(row) == snapshot(external)


@pytest.mark.parametrize("reversed_order", [False, True])
async def test_content_capture_promotes_external_and_replay_keeps_one_complete_record(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment, reversed_order
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, storage, objects = native_environment
    events = capture_events(raw, content_safety_clock)
    ordered = list(reversed(events)) if reversed_order else events
    for audit_event in ordered:
        assert await writer.write(audit_event)
    for audit_event in events:
        assert await writer.write(audit_event)
    with tenant_session(content_safety_engine) as session:
        repository = DshModelAuditWriteRepository(session)
        row = repository.request(raw["backend_request_id"])
        assert_promoted(row, external, events[0].metadata, "CONTENT")
        assert (row.model_result, row.response_result, row.usage_settlement) == ("SUCCEEDED", "COMPLETED", "SETTLED")
        assert row.content_status == "COMPLETE" and row.audit_status == "NORMAL"
        assert row.group_index_pending
        manifest, occurrences, contents = repository.facts(row.request_id)
        assert len(occurrences) == sum(value["count"] for value in manifest.channels.values())
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1
        scope = AuditScope(101, 11, "CONVERSATION", row.conversation_id)
        recovered = []
        for occurrence in occurrences:
            content = contents[occurrence.content_id]
            reference = StoredAuditBlock(
                **{
                    name: getattr(content, name)
                    for name in ("object_key", "key_version", "digest", "byte_length", "scope_key", "encoding_version")
                }
            )
            recovered.append(await storage.open_verified_block(scope, reference))
        assert b"synthetic confidential input" in b"".join(recovered)
        assert b"synthetic model answer" in b"".join(recovered)
        assert session.exec(select(DshModelCall)).all() == []
        assert session.exec(select(DshMonthlyUsage)).all() == []
    assert objects.data and all(value.startswith(b"DMA1") for value in objects.data.values())
    assert all(b"synthetic confidential input" not in value for value in objects.data.values())


async def test_metadata_promotion_has_no_original_body_and_keeps_unsettled_usage_unknown(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, objects = native_environment
    events = capture_events(raw, content_safety_clock, mode="METADATA")
    for audit_event in events:
        if audit_event.kind != "usage":
            assert await writer.write(audit_event)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert_promoted(row, external, events[0].metadata, "METADATA")
        assert row.content_status == "NOT_CAPTURED" and row.model_result == "SUCCEEDED"
        assert row.response_result == "COMPLETED" and row.usage_settlement == "PENDING"
        assert session.exec(select(DshModelAuditOccurrence)).all() == []
        assert session.exec(select(DshModelAuditContent)).all() == []
        assert session.exec(select(DshModelCall)).all() == []
    assert objects.data == {}


@pytest.mark.parametrize("kind", ["entered", "terminal", "response", "usage"])
async def test_any_native_control_can_arrive_first_and_initialize_only_its_observed_axis(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment, kind
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    audit_event = next(item for item in capture_events(raw, content_safety_clock, mode="METADATA") if item.kind == kind)
    assert await writer.write(audit_event)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert_promoted(row, external, audit_event.metadata, "METADATA")
        assert row.model_result == ("SUCCEEDED" if kind == "terminal" else "RUNNING")
        assert row.response_result == ("COMPLETED" if kind == "response" else "RUNNING")
        assert row.usage_settlement == ("SETTLED" if kind == "usage" else "PENDING")


async def test_real_body_batch_can_be_first_native_write_and_preserves_safety_projection(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    events = capture_events(raw, content_safety_clock)
    bodies = [item for item in events if item.kind == "body"]
    buffer = AuditBodyBuffer(ControlledAuditQueue(), events[0])
    for item in bodies:
        assert buffer.append(item.channel, item.sequence, item.unit_index, item.body)
    await writer.write_body_batch(buffer)
    assert writer.written == len(bodies) and writer.failed == 0
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert_promoted(row, external, events[0].metadata, "CONTENT")
        assert row.content_status == "PENDING"
        assert len(session.exec(select(DshModelAuditOccurrence)).all()) == len(bodies)
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1


async def test_promotion_does_not_reset_already_indexed_sensitive_hit_or_its_revision(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw, _ = safety_first(content_safety_engine, content_safety_event)
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        row.group_indexed_sensitive_hit = True
        row.group_index_pending = False
        session.add(row)
    with tenant_session(content_safety_engine) as session:
        external = session.get(DshModelAuditRequest, raw["backend_request_id"])
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode="METADATA")[0]
    assert await writer.write(entered)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert_promoted(row, external, entered.metadata, "METADATA")
        assert row.group_indexed_sensitive_hit and row.group_index_pending


@pytest.mark.parametrize("kind", ["body", "terminal"])
async def test_failed_commit_rolls_back_promotion_body_reference_and_manifest_together(
    content_safety_engine, content_safety_event, content_safety_clock, content_safety_faults, native_environment, kind
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    native_event = next(item for item in capture_events(raw, content_safety_clock) if item.kind == kind)
    content_safety_faults.fail_next("native_before_commit")
    assert not await writer.write(native_event)
    assert content_safety_faults.pending["native_before_commit"] == 0
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "EXTERNAL_SAFETY" and row.effective_mode is None
        assert row.model_entered is None and row.model_started_at is None
        assert row.session_id is None and row.model_name == ""
        assert row.conversation_id is None and row.model_result is None
        assert snapshot(row) == snapshot(external)
        assert session.exec(select(DshModelAuditManifest)).all() == []
        assert session.exec(select(DshModelAuditOccurrence)).all() == []
        assert session.exec(select(DshModelAuditContent)).all() == []
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1
    assert await writer.write(native_event)


async def test_matching_confirmed_external_identity_can_promote_with_subagent_hints(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    hints = {
        "conversation_id": "confirmed-child",
        "request_kind": "compaction",
        "session_origin": "subagent",
        "parent_conversation_id": "confirmed-parent",
    }
    session_id = "10100000-0000-4000-8000-000000000099"
    raw, external = safety_first(content_safety_engine, content_safety_event, session_id=session_id, conversation=hints)
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode="METADATA", session_id=session_id, **hints)[0]
    assert await writer.write(entered)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert_promoted(row, external, entered.metadata, "METADATA")
        assert row.association_status == "ASSOCIATED" and row.group_index_pending


async def test_later_native_replay_cannot_move_either_confirmed_start_time(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode="METADATA")[0]
    assert await writer.write(entered)
    later = capture_events(
        raw,
        content_safety_clock,
        mode="METADATA",
        started_at=content_safety_clock.now() + timedelta(seconds=100),
    )[0]
    assert await writer.write(later)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert_promoted(row, external, entered.metadata, "METADATA")
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1


@pytest.mark.parametrize("field,value", [("user_id", 22), ("model_id", 8)])
async def test_native_foreign_owner_is_rejected_without_losing_the_external_fact(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment, field, value
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode="METADATA", **{field: value})[0]
    assert not await writer.write(entered)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "EXTERNAL_SAFETY" and (row.user_id, row.model_id) == (11, 7)
        assert row.effective_mode is None and snapshot(row) == snapshot(external)
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


async def test_foreign_tenant_native_pk_collision_cannot_promote_an_invisible_row(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw, external = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode="METADATA", tenant_id=202, user_id=22, model_id=8)[0]
    assert not await writer.write(entered)
    with tenant_session(content_safety_engine, 202) as session:
        assert session.exec(select(DshModelAuditRequest)).all() == []
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "EXTERNAL_SAFETY" and snapshot(row) == snapshot(external)
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "10100000-0000-4000-8000-000000000088"),
        ("conversation_id", "conflicting-conversation"),
    ],
)
async def test_confirmed_external_nonnull_identity_conflict_cannot_be_treated_as_unknown(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment, field, value
):
    raw, external = safety_first(
        content_safety_engine,
        content_safety_event,
        session_id="10100000-0000-4000-8000-000000000099",
        conversation={
            "conversation_id": "confirmed-native-conversation",
            "request_kind": "chat",
            "session_origin": "main",
        },
    )
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode="METADATA", **{field: value})[0]
    assert not await writer.write(entered)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "EXTERNAL_SAFETY" and row.effective_mode is None
        assert row.session_id == external.session_id and row.conversation_id == external.conversation_id
        assert snapshot(row) == snapshot(external)
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


@pytest.mark.parametrize("field", ["session_id", "conversation_id"])
async def test_existing_model_null_identity_retains_original_strict_conflict_rule(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment, field
):
    writer, _, _ = native_environment
    raw = output_event(content_safety_event)
    entered = capture_events(raw, content_safety_clock, mode="METADATA")[0]
    assert await writer.write(entered)
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(DshModelAuditRequest, entered.request_id)
        setattr(row, field, None)
        session.add(row)
    assert not await writer.write(entered)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, entered.request_id)
        assert row.record_origin == "MODEL" and getattr(row, field) is None
        assert not row.has_sensitive_hit and row.content_safety_state == "UNREPORTED"
        assert session.exec(select(DshContentSafetyEvent)).all() == []


async def test_native_without_gateway_still_writes_normally_and_does_not_invent_safety_results(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    writer, _, _ = native_environment
    raw = output_event(content_safety_event, backend_request_id=str(uuid4()))
    events = capture_events(raw, content_safety_clock, mode="METADATA")
    for audit_event in events:
        assert await writer.write(audit_event)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "MODEL" and row.effective_mode == "METADATA"
        assert row.model_result == "SUCCEEDED" and row.usage_settlement == "SETTLED"
        assert not row.has_sensitive_hit and row.content_safety_state == "UNREPORTED"
        assert row.input_safety_version == 0 and row.output_safety_version == 0
        assert row.safety_source_id is None and row.safety_gateway_request_id is None
        assert session.exec(select(DshContentSafetyEvent)).all() == []
