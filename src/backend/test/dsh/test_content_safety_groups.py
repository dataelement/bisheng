"""Coverage AC: AC-38, AC-41, AC-47, AC-48, AC-52.

Real repository/service transactions; SQLite does not prove dual-DB locking.
"""

from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation as Group
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState
from bisheng.dsh.domain.repositories import content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.schemas.model_audit_status import refresh_audit_status
from bisheng.dsh.domain.services.model_audit_projection import project_audit_groups
from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key
from test.dsh.test_content_safety_merge import committed_merge, output_event
from test.dsh.test_content_safety_native_writer import capture_events
from test.dsh.test_content_safety_native_writer import native_environment as native_environment
from test.dsh.test_content_safety_repository import tenant_session


def native(factory, *, conversation="synthetic-conversation", **changes):
    values = {
        "conversation_id": conversation,
        "conversation_key": conversation_key(101, 11, conversation) if conversation else None,
        "conversation_id_digest": sha256(conversation.encode()).hexdigest() if conversation else None,
        "association_status": "ASSOCIATED" if conversation else "UNASSOCIATED",
        "model_name_digest": sha256(b"synthetic-model").hexdigest(),
        "model_result": "SUCCEEDED",
        "response_result": "COMPLETED",
        "usage_settlement": "SETTLED",
        "content_status": "NOT_CAPTURED",
        "group_index_pending": True,
    }
    values.update(changes)
    row = factory(**values)
    refresh_audit_status(row)
    return row


def project(engine, request_id, *, tenant=101, now=None):
    with tenant_session(engine, tenant) as session, session.begin():
        return DshModelAuditQueryRepository(session).project_request(request_id, now=now)


def summary(engine, key):
    with tenant_session(engine) as session:
        group = DshModelAuditQueryRepository(session).group(key)
        return (
            None
            if group is None
            else (group.request_count, group.abnormal_count, group.sensitive_hit_count, group.has_sensitive_hit)
        )


def queries(engine):
    @contextmanager
    def scope():
        with strict_tenant_filter(), Session(engine, expire_on_commit=False) as session, session.begin():
            yield DshModelAuditQueryRepository(session)

    return DshModelAuditQueryService(None, scope)


def test_unchanged_model_status_late_hit_updates_once_and_dirties_safety_tree(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_clock
):
    engine = content_safety_engine
    row = native(content_safety_native_audit)
    with tenant_session(engine) as session, session.begin():
        session.add(row)
    assert project(engine, row.request_id, now=content_safety_clock.now())
    assert summary(engine, row.conversation_key) == (1, 0, 0, False)
    with tenant_session(engine) as session:
        previous = session.get(DshAuditTreeState, 101).safety_summary_revision
    raw = output_event(content_safety_event, backend_request_id=row.request_id)
    committed_merge(engine, content_safety_projection, raw)
    with tenant_session(engine) as session:
        saved = session.get(Request, row.request_id)
        assert saved.audit_status == saved.group_indexed_status == "NORMAL"
        assert saved.group_index_pending and saved.has_sensitive_hit
    later = content_safety_clock.now() + timedelta(seconds=10)
    assert project(engine, row.request_id, now=later)
    assert summary(engine, row.conversation_key) == (1, 0, 1, True)
    with tenant_session(engine) as session:
        saved = session.get(Request, row.request_id)
        assert saved.group_indexed_sensitive_hit and not saved.group_index_pending
        assert session.get(Group, row.conversation_key).updated_at.replace(tzinfo=None) == later.replace(tzinfo=None)
        assert session.get(DshAuditTreeState, 101).safety_summary_revision > previous
    committed_merge(engine, content_safety_projection, raw)
    assert not project(engine, row.request_id)
    assert summary(engine, row.conversation_key) == (1, 0, 1, True)


def test_external_hit_is_one_entry_without_manufacturing_model_abnormality(content_safety_engine, content_safety_event):
    raw = content_safety_event(session_id=None)
    _, external, _ = committed_merge(content_safety_engine, content_safety_projection, raw)
    assert external.audit_status == "NOT_APPLICABLE" and external.model_entered is False
    assert project(content_safety_engine, external.request_id)
    assert summary(content_safety_engine, external.conversation_key) == (1, 0, 1, True)
    assert not project(content_safety_engine, external.request_id)
    with tenant_session(content_safety_engine) as session:
        saved = session.get(Request, external.request_id)
        assert saved.group_indexed_status == "NOT_APPLICABLE" and saved.group_indexed_sensitive_hit
        assert saved.model_result is None and saved.usage_settlement is None
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


async def test_external_promotion_and_status_changes_never_add_duplicate_entry_or_hit(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw = output_event(content_safety_event, session_id=None)
    _, external, _ = committed_merge(content_safety_engine, content_safety_projection, raw)
    assert project(content_safety_engine, external.request_id)
    writer, _, _ = native_environment
    for item in capture_events(raw, content_safety_clock, mode="METADATA", conversation_id="synthetic-conversation"):
        assert await writer.write(item)
    assert project(content_safety_engine, external.request_id)
    assert summary(content_safety_engine, external.conversation_key) == (1, 0, 1, True)
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(Request, external.request_id)
        row.model_result = "FAILED"
        refresh_audit_status(row)
        session.add(row)
    assert project(content_safety_engine, external.request_id)
    assert summary(content_safety_engine, external.conversation_key) == (1, 1, 1, True)
    assert not project(content_safety_engine, external.request_id)


async def test_unassociated_pending_is_processed_and_native_association_can_later_count_once(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment
):
    raw = output_event(content_safety_event, session_id=None, conversation=None)
    _, external, _ = committed_merge(content_safety_engine, content_safety_projection, raw)
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(Request, external.request_id)
        row.group_index_pending = True
        session.add(row)
    assert project(content_safety_engine, external.request_id)
    with tenant_session(content_safety_engine) as session:
        row = session.get(Request, external.request_id)
        assert not row.group_index_pending and row.group_indexed_status is None
        assert not row.group_indexed_sensitive_hit and session.exec(select(Group)).all() == []
    assert not project(content_safety_engine, external.request_id)
    writer, _, _ = native_environment
    assert await writer.write(capture_events(raw, content_safety_clock, mode="METADATA")[0])
    with tenant_session(content_safety_engine) as session:
        row = session.get(Request, external.request_id)
        key = row.conversation_key
        assert key and row.group_index_pending
    assert project(content_safety_engine, external.request_id)
    assert summary(content_safety_engine, key) == (1, 0, 1, True)
    assert not project(content_safety_engine, external.request_id)


def test_both_hit_flags_and_later_events_count_the_request_once(
    content_safety_engine, content_safety_event, content_safety_native_audit
):
    row = native(
        content_safety_native_audit,
        input_sensitive_hit=True,
        output_sensitive_hit=True,
        has_sensitive_hit=True,
        content_safety_state="BLOCKED",
    )
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(row)
    assert project(content_safety_engine, row.request_id)
    assert summary(content_safety_engine, row.conversation_key) == (1, 0, 1, True)
    raw = output_event(content_safety_event, backend_request_id=row.request_id)
    committed_merge(content_safety_engine, content_safety_projection, raw)
    project(content_safety_engine, row.request_id)
    drain = {**raw, "event_id": str(uuid4()), "event_kind": "DRAIN", "event_version": 2, "drain_status": "FINISHED"}
    committed_merge(content_safety_engine, content_safety_projection, drain)
    project(content_safety_engine, row.request_id)
    assert summary(content_safety_engine, row.conversation_key) == (1, 0, 1, True)


def test_rollback_preserves_pending_and_retry_neither_duplicates_nor_negates_counts(
    content_safety_engine, content_safety_event
):
    _, row, _ = committed_merge(content_safety_engine, content_safety_projection, content_safety_event(session_id=None))
    with pytest.raises(RuntimeError, match="synthetic rollback"):
        with tenant_session(content_safety_engine) as session, session.begin():
            assert DshModelAuditQueryRepository(session).project_request(row.request_id)
            session.flush()
            raise RuntimeError("synthetic rollback")
    with tenant_session(content_safety_engine) as session:
        saved = session.get(Request, row.request_id)
        assert saved.group_index_pending and not saved.group_indexed_sensitive_hit
        assert session.exec(select(Group)).all() == []
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1
    assert project(content_safety_engine, row.request_id)
    assert summary(content_safety_engine, row.conversation_key) == (1, 0, 1, True)
    assert not project(content_safety_engine, row.request_id)


def test_foreign_tenant_projection_cannot_change_the_owned_entry(content_safety_engine, content_safety_event):
    _, row, _ = committed_merge(content_safety_engine, content_safety_projection, content_safety_event(session_id=None))
    assert not project(content_safety_engine, row.request_id, tenant=202)
    with tenant_session(content_safety_engine, 202) as session:
        assert session.exec(select(Group)).all() == []
    assert project(content_safety_engine, row.request_id)
    assert summary(content_safety_engine, row.conversation_key) == (1, 0, 1, True)


def test_safety_and_model_abnormality_counters_are_independent_in_mixed_groups(
    content_safety_engine, content_safety_event, content_safety_native_audit
):
    _, external, _ = committed_merge(
        content_safety_engine, content_safety_projection, content_safety_event(session_id=None)
    )
    ordinary, failed = native(content_safety_native_audit), native(content_safety_native_audit, model_result="FAILED")
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add_all([ordinary, failed])
    for request_id in (external.request_id, ordinary.request_id, failed.request_id):
        assert project(content_safety_engine, request_id)
    assert summary(content_safety_engine, external.conversation_key) == (3, 1, 1, True)


def test_model_not_applicable_status_is_not_an_external_source_shortcut(
    content_safety_engine, content_safety_native_audit
):
    row = native(content_safety_native_audit)
    row.audit_status = "NOT_APPLICABLE"
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(row)
    with pytest.raises(ValueError):
        project(content_safety_engine, row.request_id)
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(Group)).all() == []
        assert session.get(Request, row.request_id).group_index_pending


def test_model_status_refresh_independently_marks_safety_changes_dirty(content_safety_native_audit):
    row = native(content_safety_native_audit, group_index_pending=False, group_indexed_status="NORMAL")
    row.has_sensitive_hit = row.input_sensitive_hit = True
    row.content_safety_state = "BLOCKED"
    row.safety_projection_version += 1
    refresh_audit_status(row)
    assert row.audit_status == "NORMAL" and row.group_index_pending


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_projection_candidate_batch_limit_is_positive_and_at_most_two_hundred(content_safety_engine, limit):
    with tenant_session(content_safety_engine) as session, pytest.raises(ValueError):
        DshModelAuditQueryRepository(session).projection_candidates(limit=limit)


def test_projection_updates_fence_tenant_and_source_revision(content_safety_engine, content_safety_native_audit):
    row = native(content_safety_native_audit, has_sensitive_hit=True, output_sensitive_hit=True)
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(row)
    writes = []

    def observed(_connection, _cursor, statement, _parameters, _context, _many):
        upper = statement.upper()
        if upper.startswith(("UPDATE DSH_MODEL_AUDIT_REQUEST", "UPDATE DSH_MODEL_AUDIT_CONVERSATION")):
            writes.append(upper)

    event.listen(content_safety_engine, "before_cursor_execute", observed)
    try:
        assert project(content_safety_engine, row.request_id)
    finally:
        event.remove(content_safety_engine, "before_cursor_execute", observed)
    assert writes
    for statement in writes:
        where = statement.split("WHERE", 1)[1]
        assert "TENANT_ID" in where
        if statement.startswith("UPDATE DSH_MODEL_AUDIT_REQUEST"):
            assert any(token in where for token in ("SAFETY_PROJECTION_VERSION", "STATE_VERSION", "LEASE"))


async def test_projection_service_isolates_database_failure_and_retries_durable_pending(
    content_safety_engine, content_safety_native_audit
):
    first = native(content_safety_native_audit, request_id=str(UUID(int=1)), conversation="first")
    second = native(content_safety_native_audit, request_id=str(UUID(int=2)), conversation="second")
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add_all([first, second])
    failures = [True]

    def fail_write(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            failures
            and "DSH_MODEL_AUDIT_CONVERSATION" in statement.upper()
            and statement.upper().startswith(("INSERT", "UPDATE"))
        ):
            failures.pop()
            raise RuntimeError("synthetic projection database outage")

    event.listen(content_safety_engine, "before_cursor_execute", fail_write)
    service = queries(content_safety_engine)
    try:
        _, changed = await project_audit_groups(service, 101)
    finally:
        event.remove(content_safety_engine, "before_cursor_execute", fail_write)
    assert not failures and changed == 1
    with tenant_session(content_safety_engine) as session:
        assert session.get(Request, first.request_id).group_index_pending
        assert not session.get(Request, second.request_id).group_index_pending
    _, changed = await project_audit_groups(service, 101)
    assert changed == 1
    assert summary(content_safety_engine, first.conversation_key) == (1, 0, 0, False)
    assert summary(content_safety_engine, second.conversation_key) == (1, 0, 0, False)


async def test_service_walks_durable_pending_in_bounded_batches(
    content_safety_engine, content_safety_native_audit, monkeypatch
):
    rows = [native(content_safety_native_audit, request_id=str(UUID(int=index + 1))) for index in range(205)]
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add_all(rows)
    service = queries(content_safety_engine)
    original, sizes = service.execute, []

    async def tracked(tenant, function):
        value = await original(tenant, function)
        if isinstance(value, list):
            sizes.append(len(value))
        return value

    monkeypatch.setattr(service, "execute", tracked)
    cursor, changed, rounds = None, 0, 0
    while True:
        cursor, count = await project_audit_groups(service, 101, cursor or "")
        changed += count
        rounds += 1
        if cursor is None:
            break
        assert rounds < 10
    assert changed == 205 and all(size <= 200 for size in sizes)
    assert summary(content_safety_engine, rows[0].conversation_key) == (205, 0, 0, False)
    assert await project_audit_groups(service, 101) == (None, 0)
