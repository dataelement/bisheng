"""Coverage AC: AC-03, AC-35, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-58.

Exercise the real repositories and SQLite transaction/session ports. Injected SQL
faults prove orchestration boundaries, never MySQL/DM8 concurrency or durability.
The receiver consumes original signed event mappings, not cleaned DTO dumps.
"""

import asyncio
import importlib
import sqlite3
import threading
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import (
    DshContentSafetyAuthError,
    DshContentSafetyConflictError,
    DshContentSafetyExpiredError,
    DshContentSafetyInvalidEventError,
    DshContentSafetyUnavailableError,
)
from bisheng.core.context import tenant as context
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
from bisheng.dsh.domain.repositories import content_safety
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyReceipt
from bisheng.dsh.domain.services.profile import profile_scope
from test.dsh.test_content_safety_repository import decoded, tenant_session, wire_hash


def ingest_port():
    return importlib.import_module("bisheng.dsh.domain.services.content_safety_ingest")


def source(port, raw, **changes):
    values = {"source_id": raw["source_id"], "tenant_id": int(raw["tenant_id"])}
    values.update(changes)
    return port.VerifiedSource(**values)


def scope_snapshot():
    return (
        context.get_current_tenant_id(),
        context.get_admin_scope_tenant_id(),
        context.get_visible_tenant_ids(),
        context.is_tenant_filter_bypassed(),
    )


class SessionPort:
    """Observe real sessions; optional callbacks inject transport/database faults."""

    def __init__(self, engine):
        self.engine = engine
        self.sessions = []
        self.scopes = []
        self.thread_ids = []
        self.failed_reads = []
        self.commits = 0
        self.before_commit = None
        self.after_commit = None
        self.after_close = None

    def __call__(self):
        port = self

        class ObservedSession(Session):
            def close(self):
                super().close()
                if port.after_close is not None:
                    port.after_close(self)

        session = ObservedSession(self.engine, expire_on_commit=False)
        self.sessions.append(session)
        self.scopes.append(scope_snapshot())
        self.thread_ids.append(threading.get_ident())

        def observed_read(state):
            self.scopes.append(scope_snapshot())
            if not state.session.is_active:
                self.failed_reads.append(state.session)

        def before_commit(current):
            if self.before_commit is not None:
                self.before_commit(current)

        def after_commit(current):
            self.commits += 1
            if self.after_commit is not None:
                self.after_commit(current)

        sql_event.listen(session, "do_orm_execute", observed_read)
        sql_event.listen(session, "before_commit", before_commit)
        sql_event.listen(session, "after_commit", after_commit)
        return session


def rows(engine, tenant_id=101):
    with tenant_session(engine, tenant_id) as session:
        return session.exec(select(DshContentSafetyEvent)).all(), session.exec(select(DshModelAuditRequest)).all()


def assert_receipt(receipt, raw, *, duplicate=False, associated=True):
    assert isinstance(receipt, ContentSafetyReceipt)
    assert receipt.receipt == "COMMITTED" and receipt.event_id == raw["event_id"]
    assert receipt.duplicate is duplicate
    assert receipt.association_status == ("ASSOCIATED" if associated else "UNASSOCIATED")
    assert receipt.audit_request_id == (raw["backend_request_id"] or raw["gateway_request_id"] if associated else None)


async def test_commit_persists_fact_and_summary_before_returning_receipt(content_safety_engine, content_safety_event):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)
    service = port.ContentSafetyIngestService(sessions)
    raw = content_safety_event()
    receipt = await service.ingest(raw, source(port, raw))
    assert_receipt(receipt, raw)
    facts, audits = rows(content_safety_engine)
    assert sessions.commits == 1 and len(facts) == len(audits) == 1
    assert facts[0].audit_request_id == audits[0].request_id
    assert facts[0].payload_hash == wire_hash(raw)
    assert audits[0].has_sensitive_hit and audits[0].record_origin == "EXTERNAL_SAFETY"
    assert audits[0].effective_mode is None and audits[0].model_result is None
    assert audits[0].usage_settlement is None and audits[0].model_entered is False


async def test_receipt_waits_for_commit_without_blocking_event_loop(content_safety_engine, content_safety_event):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)
    entered, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    def hold_commit(session):
        session.flush()
        entered.set()
        assert release.wait(3), "The test must release the real SQL commit"

    sessions.before_commit = hold_commit
    raw = content_safety_event()
    task = asyncio.create_task(port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw)))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert not task.done() and sessions.commits == 0
        assert sessions.thread_ids and all(value != loop_thread for value in sessions.thread_ids)
    finally:
        release.set()
        receipt = await task
    assert_receipt(receipt, raw)
    assert sessions.commits == 1


@pytest.mark.parametrize(
    "failure", [OperationalError("synthetic", {}, Exception("SQL unavailable")), TimeoutError("SQL timeout")]
)
async def test_failed_or_timed_out_commit_never_returns_ack(content_safety_engine, content_safety_event, failure):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)

    def fail_commit(_session):
        raise failure

    sessions.before_commit = fail_commit
    raw = content_safety_event()
    with pytest.raises(DshContentSafetyUnavailableError):
        await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    assert sessions.commits == 0
    assert rows(content_safety_engine) == ([], [])


async def test_lost_response_retry_deduplicates_already_committed_projection(
    content_safety_engine, content_safety_event
):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)
    raw = content_safety_event()
    first_service = port.ContentSafetyIngestService(sessions)
    await first_service.ingest(raw, source(port, raw))
    version = rows(content_safety_engine)[1][0].safety_projection_version
    # Discard the first response and reconstruct the service, as after a receiver restart.
    receipt = await port.ContentSafetyIngestService(sessions).ingest(deepcopy(raw), source(port, raw))
    assert_receipt(receipt, raw, duplicate=True)
    facts, audits = rows(content_safety_engine)
    assert len(facts) == len(audits) == 1 and audits[0].safety_projection_version == version


async def test_postcommit_timeout_is_not_ack_and_retry_finds_durable_fact(content_safety_engine, content_safety_event):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)

    def lose_commit_confirmation(_session):
        sessions.after_commit = None
        raise TimeoutError("Synthetic confirmation loss after durable commit")

    sessions.after_commit = lose_commit_confirmation
    raw = content_safety_event()
    with pytest.raises(DshContentSafetyUnavailableError):
        await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    assert len(rows(content_safety_engine)[0]) == 1
    receipt = await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    assert_receipt(receipt, raw, duplicate=True)
    assert len(rows(content_safety_engine)[1]) == 1


@pytest.mark.parametrize("field", ["backend_request_id", "session_id", "conversation"])
async def test_original_omission_and_explicit_null_conflict_before_dto_defaults(
    content_safety_engine, content_safety_event, field
):
    port = ingest_port()
    raw = content_safety_event(**{field: None})
    omitted = deepcopy(raw)
    omitted.pop(field)
    assert decoded(raw) == decoded(omitted) and wire_hash(raw) != wire_hash(omitted)
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(omitted, source(port, omitted))
    with pytest.raises(DshContentSafetyConflictError):
        await service.ingest(raw, source(port, raw))
    assert len(rows(content_safety_engine)[0]) == 1


async def test_hint_cleaning_does_not_erase_original_hash_conflicts(content_safety_engine, content_safety_event):
    port = ingest_port()
    raw = content_safety_event(conversation={"conversation_id": "", "request_kind": "unknown"})
    changed = deepcopy(raw)
    changed["conversation"] = {"conversation_id": "", "request_kind": "also-unknown"}
    assert decoded(raw) == decoded(changed)
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(raw, source(port, raw))
    with pytest.raises(DshContentSafetyConflictError):
        await service.ingest(changed, source(port, changed))
    assert rows(content_safety_engine)[0][0].payload_hash == wire_hash(raw)


async def test_canonical_key_order_retries_but_timestamp_spelling_is_original_fact(
    content_safety_engine, content_safety_event
):
    port = ingest_port()
    raw = content_safety_event()
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(raw, source(port, raw))
    reordered = dict(reversed(list(raw.items())))
    assert_receipt(await service.ingest(reordered, source(port, raw)), raw, duplicate=True)
    changed = deepcopy(raw)
    changed["occurred_at"] = raw["occurred_at"].replace("Z", "+00:00")
    with pytest.raises(DshContentSafetyConflictError):
        await service.ingest(changed, source(port, changed))


async def test_receipt_echoes_wire_uuid_spelling_while_storage_is_canonical(
    content_safety_engine, content_safety_event
):
    port = ingest_port()
    raw = content_safety_event()
    raw["event_id"] = raw["event_id"].upper()
    receipt = await port.ContentSafetyIngestService(SessionPort(content_safety_engine)).ingest(raw, source(port, raw))
    assert_receipt(receipt, raw)
    assert rows(content_safety_engine)[0][0].event_id == raw["event_id"].lower()


@pytest.mark.parametrize("changes", [{"source_id": "other-gateway"}, {"tenant_id": 202}])
async def test_verified_source_mismatch_rejected_before_any_sql(content_safety_engine, content_safety_event, changes):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)
    raw = content_safety_event()
    with pytest.raises(DshContentSafetyAuthError):
        await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw, **changes))
    assert sessions.sessions == [] and rows(content_safety_engine) == ([], [])


@pytest.mark.parametrize("fail_commit", [False, True])
async def test_browser_bypass_and_admin_scope_are_cleared_in_sql_thread_then_restored(
    content_safety_engine, content_safety_event, fail_commit
):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)
    raw = content_safety_event()
    if fail_commit:

        def fail_before_commit(_session):
            raise TimeoutError("Synthetic SQL timeout")

        sessions.before_commit = fail_before_commit
    tokens = [
        context.set_current_tenant_id(202),
        context.set_admin_scope_tenant_id(303),
        context.set_visible_tenant_ids(frozenset({101, 202, 303})),
        context._bypass_tenant_filter.set(True),
    ]
    before = scope_snapshot()
    try:
        service = port.ContentSafetyIngestService(sessions)
        if fail_commit:
            with pytest.raises(DshContentSafetyUnavailableError):
                await service.ingest(raw, source(port, raw))
        else:
            assert_receipt(await service.ingest(raw, source(port, raw)), raw)
        assert scope_snapshot() == before
        assert sessions.scopes and all(value == (101, None, frozenset({101}), False) for value in sessions.scopes)
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


async def test_unknown_backend_id_commits_only_unassociated_fact(content_safety_engine, content_safety_event):
    port = ingest_port()
    raw = content_safety_event(
        forwarded=True,
        backend_request_id=None,
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        drain_status="RUNNING",
    )
    receipt = await port.ContentSafetyIngestService(SessionPort(content_safety_engine)).ingest(raw, source(port, raw))
    assert_receipt(receipt, raw, associated=False)
    facts, audits = rows(content_safety_engine)
    assert len(facts) == 1 and audits == [] and facts[0].association_status == "UNASSOCIATED"


async def test_changed_trusted_owner_is_accepted_without_overwriting_native_owner(
    content_safety_engine, content_safety_event, content_safety_native_audit
):
    port = ingest_port()
    native = content_safety_native_audit()
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
    raw = content_safety_event(
        forwarded=True,
        backend_request_id=native.request_id,
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        drain_status="RUNNING",
    )
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    assert_receipt(await service.ingest(raw, source(port, raw)), raw)
    changed = deepcopy(raw)
    changed.update(event_id=str(uuid4()), event_version=2, user_id="22", model_id="8", session_id=None)
    receipt = await service.ingest(changed, source(port, changed))
    assert_receipt(receipt, changed, associated=False)
    facts, audits = rows(content_safety_engine)
    assert len(facts) == 2 and len(audits) == 1
    assert (audits[0].user_id, audits[0].model_id, audits[0].session_id) == (11, 7, native.session_id)
    assert audits[0].has_sensitive_hit and audits[0].model_entered is True


async def test_later_snapshot_cannot_clear_confirmed_hit(content_safety_engine, content_safety_event):
    port = ingest_port()
    raw = content_safety_event(
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        forwarded=True,
        backend_request_id=str(uuid4()),
        drain_status="RUNNING",
    )
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(raw, source(port, raw))
    later = deepcopy(raw)
    later.update(
        event_id=str(uuid4()), event_kind="DRAIN", event_version=2, drain_status="FINISHED", hit_count=0, rule_refs=[]
    )
    await service.ingest(later, source(port, later))
    facts, audits = rows(content_safety_engine)
    assert len(facts) == 2 and len(audits) == 1
    assert audits[0].has_sensitive_hit and audits[0].output_sensitive_hit
    assert audits[0].content_safety_state == "BLOCKED"
    assert next(fact for fact in facts if fact.event_id == later["event_id"]).drain_status == "FINISHED"


async def test_new_version_can_move_to_another_verified_tenant_without_identity_freeze(
    content_safety_engine, content_safety_event
):
    port = ingest_port()
    raw = content_safety_event(forwarded=True, backend_request_id=None)
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(raw, source(port, raw))
    changed = deepcopy(raw)
    changed.update(event_id=str(uuid4()), event_version=2, tenant_id="202", user_id="22", model_id="8")
    assert_receipt(await service.ingest(changed, source(port, changed)), changed, associated=False)
    assert len(rows(content_safety_engine, 101)[0]) == len(rows(content_safety_engine, 202)[0]) == 1


async def test_new_event_below_retention_watermark_is_410_but_existing_retry_survives(
    content_safety_engine, content_safety_event, content_safety_clock
):
    port = ingest_port()
    raw = content_safety_event(forwarded=True, backend_request_id=None)
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(raw, source(port, raw))
    with tenant_session(content_safety_engine) as session, session.begin():
        setting = session.exec(select(DshModelAuditSetting)).one()
        setting.audit_deleted_before = content_safety_clock.now() + timedelta(seconds=1)
        session.add(setting)
    assert_receipt(await service.ingest(raw, source(port, raw)), raw, duplicate=True, associated=False)
    old = content_safety_event(forwarded=True, backend_request_id=None)
    with pytest.raises(DshContentSafetyExpiredError):
        await service.ingest(old, source(port, old))
    assert len(rows(content_safety_engine)[0]) == 1


async def test_event_version_collision_is_conflict_not_duplicate(content_safety_engine, content_safety_event):
    port = ingest_port()
    raw = content_safety_event()
    service = port.ContentSafetyIngestService(SessionPort(content_safety_engine))
    await service.ingest(raw, source(port, raw))
    other = deepcopy(raw)
    other["event_id"] = str(uuid4())
    with pytest.raises(DshContentSafetyConflictError):
        await service.ingest(other, source(port, other))
    assert len(rows(content_safety_engine)[0]) == 1


async def test_append_unique_race_exits_failed_transaction_and_remerges_in_fresh_session(
    content_safety_engine, content_safety_event
):
    port = ingest_port()
    raw = content_safety_event()
    sessions = SessionPort(content_safety_engine)
    armed, winner = True, False

    def collide(_connection, _cursor, statement, parameters, _execution_context, _many):
        nonlocal armed
        if armed and statement.lstrip().upper().startswith("INSERT INTO DSH_CONTENT_SAFETY_EVENT"):
            armed = False
            raise IntegrityError(statement, parameters, sqlite3.IntegrityError("Synthetic racing event uniqueness"))

    def commit_competitor_after_failed_session_closed(closed):
        nonlocal winner
        if not armed and not winner and closed is sessions.sessions[0]:
            winner = True
            with profile_scope(101), Session(content_safety_engine) as competing, competing.begin():
                # A real competing transaction commits only the immutable event; receiver retry must finish its projection.
                content_safety.append_event(competing, decoded(raw), wire_hash(raw))

    sessions.after_close = commit_competitor_after_failed_session_closed
    sql_event.listen(content_safety_engine, "before_cursor_execute", collide)
    try:
        receipt = await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    finally:
        sql_event.remove(content_safety_engine, "before_cursor_execute", collide)
    assert_receipt(receipt, raw, duplicate=True)
    assert winner and 2 <= len(sessions.sessions) <= 3
    assert len({id(session) for session in sessions.sessions}) == len(sessions.sessions)
    assert sessions.failed_reads == []
    facts, audits = rows(content_safety_engine)
    assert len(facts) == len(audits) == 1 and facts[0].audit_request_id == audits[0].request_id
    assert audits[0].has_sensitive_hit


async def test_projection_failure_rolls_back_fact_and_summary_together(content_safety_engine, content_safety_event):
    port = ingest_port()
    raw = content_safety_event()

    def fail_projection(_connection, _cursor, statement, parameters, _execution_context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO DSH_MODEL_AUDIT_REQUEST"):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("Synthetic projection write failure")
            )

    sql_event.listen(content_safety_engine, "before_cursor_execute", fail_projection)
    try:
        with pytest.raises(DshContentSafetyUnavailableError):
            await port.ContentSafetyIngestService(SessionPort(content_safety_engine)).ingest(raw, source(port, raw))
    finally:
        sql_event.remove(content_safety_engine, "before_cursor_execute", fail_projection)
    assert rows(content_safety_engine) == ([], [])


async def test_invisible_cross_tenant_main_pk_collision_commits_event_unassociated_without_bypass(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_identities
):
    port = ingest_port()
    raw = content_safety_event()
    foreign = content_safety_native_audit(identity=content_safety_identities[1], request_id=raw["gateway_request_id"])
    with tenant_session(content_safety_engine, 202) as session, session.begin():
        session.add(foreign)
    sessions = SessionPort(content_safety_engine)
    receipt = await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    assert_receipt(receipt, raw, associated=False)
    facts, audits = rows(content_safety_engine)
    assert len(facts) == 1 and facts[0].audit_request_id is None and audits == []
    assert 2 <= len(sessions.sessions) <= 3 and sessions.failed_reads == []
    assert all(value == (101, None, frozenset({101}), False) for value in sessions.scopes)
    foreign_after = rows(content_safety_engine, 202)[1][0]
    assert foreign_after.request_id == foreign.request_id and not foreign_after.has_sensitive_hit
    assert foreign_after.record_origin == "MODEL" and foreign_after.model_entered is True


async def test_validated_raw_snapshot_does_not_follow_caller_mutation_during_commit(
    content_safety_engine, content_safety_event
):
    port = ingest_port()
    raw = content_safety_event()
    original = deepcopy(raw)
    sessions = SessionPort(content_safety_engine)
    entered, release = threading.Event(), threading.Event()

    def hold_commit(_session):
        entered.set()
        assert release.wait(3)

    sessions.before_commit = hold_commit
    task = asyncio.create_task(port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw)))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        raw["stage_results"]["input"] = "PASSED"
        raw["conversation"]["conversation_id"] = "mutated"
    finally:
        release.set()
        receipt = await task
    assert_receipt(receipt, original)
    facts, audits = rows(content_safety_engine)
    assert facts[0].payload_hash == wire_hash(original) and facts[0].stage_results["input"] == "BLOCKED"
    assert audits[0].conversation_id == original["conversation"]["conversation_id"] and audits[0].has_sensitive_hit


@pytest.mark.parametrize("changes", [{"hit_count": True}, {"conversation": {"conversation_id": 1.25}}])
async def test_invalid_raw_event_is_rejected_before_sql(content_safety_engine, content_safety_event, changes):
    port = ingest_port()
    sessions = SessionPort(content_safety_engine)
    raw = content_safety_event(**changes)
    with pytest.raises(DshContentSafetyInvalidEventError):
        await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    assert sessions.sessions == []


async def test_main_row_creation_race_retries_full_transaction_and_merges_real_winner(
    content_safety_engine, content_safety_event, content_safety_native_audit
):
    port = ingest_port()
    native = content_safety_native_audit(
        model_result="SUCCEEDED", response_result="COMPLETED", usage_settlement="SETTLED"
    )
    raw = content_safety_event(
        forwarded=True,
        backend_request_id=native.request_id,
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        drain_status="RUNNING",
    )
    sessions = SessionPort(content_safety_engine)
    armed, winner = True, False

    def collide(_connection, _cursor, statement, parameters, _execution_context, _many):
        nonlocal armed
        if armed and statement.lstrip().upper().startswith("INSERT INTO DSH_MODEL_AUDIT_REQUEST"):
            armed = False
            raise IntegrityError(statement, parameters, sqlite3.IntegrityError("Synthetic racing main-row uniqueness"))

    def commit_native_after_failed_session_closed(closed):
        nonlocal winner
        if not armed and not winner and closed is sessions.sessions[0]:
            winner = True
            with tenant_session(content_safety_engine) as competing, competing.begin():
                competing.add(native)

    sessions.after_close = commit_native_after_failed_session_closed
    sql_event.listen(content_safety_engine, "before_cursor_execute", collide)
    try:
        receipt = await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    finally:
        sql_event.remove(content_safety_engine, "before_cursor_execute", collide)
    assert_receipt(receipt, raw)
    assert winner and 2 <= len(sessions.sessions) <= 3 and sessions.failed_reads == []
    facts, audits = rows(content_safety_engine)
    assert len(facts) == len(audits) == 1 and facts[0].audit_request_id == native.request_id
    assert audits[0].record_origin == "MODEL" and audits[0].model_entered is True
    assert audits[0].model_result == "SUCCEEDED" and audits[0].usage_settlement == "SETTLED"
    assert audits[0].has_sensitive_hit and audits[0].safety_projection_version == 1


async def test_invisible_global_safety_binding_with_visible_native_target_commits_only_fact(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_identities
):
    port = ingest_port()
    raw = content_safety_event(
        event_version=2,
        forwarded=True,
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        stage_versions={"input": 1, "output": 2},
        drain_status="RUNNING",
    )
    target = content_safety_native_audit(
        model_result="SUCCEEDED", response_result="COMPLETED", usage_settlement="SETTLED"
    )
    foreign = content_safety_native_audit(
        identity=content_safety_identities[1],
        safety_source_id=raw["source_id"],
        safety_gateway_request_id=raw["gateway_request_id"],
        model_result="SUCCEEDED",
        response_result="COMPLETED",
        usage_settlement="SETTLED",
    )
    raw["backend_request_id"] = target.request_id
    for tenant_id, row in ((101, target), (202, foreign)):
        with tenant_session(content_safety_engine, tenant_id) as session, session.begin():
            session.add(row)
    sessions = SessionPort(content_safety_engine)
    receipt = await port.ContentSafetyIngestService(sessions).ingest(raw, source(port, raw))
    assert_receipt(receipt, raw, associated=False)
    facts, native_rows = rows(content_safety_engine)
    assert len(facts) == len(native_rows) == 1
    assert facts[0].payload_hash == wire_hash(raw)
    assert facts[0].audit_request_id is None and facts[0].association_status == "UNASSOCIATED"
    assert facts[0].stage_results == raw["stage_results"] and facts[0].event_version == 2
    assert 2 <= len(sessions.sessions) <= 3 and sessions.failed_reads == []
    assert all(value == (101, None, frozenset({101}), False) for value in sessions.scopes)
    for tenant_id, original in ((101, target), (202, foreign)):
        saved = rows(content_safety_engine, tenant_id)[1]
        assert len(saved) == 1 and saved[0].request_id == original.request_id
        assert (saved[0].tenant_id, saved[0].user_id, saved[0].model_id) == (
            original.tenant_id,
            original.user_id,
            original.model_id,
        )
        assert saved[0].record_origin == "MODEL" and saved[0].model_entered is True
        assert saved[0].model_result == "SUCCEEDED" and saved[0].response_result == "COMPLETED"
        assert saved[0].usage_settlement == "SETTLED"
        assert not saved[0].has_sensitive_hit and saved[0].safety_projection_version == 0
        assert (saved[0].safety_source_id, saved[0].safety_gateway_request_id) == (
            original.safety_source_id,
            original.safety_gateway_request_id,
        )
    assert rows(content_safety_engine, 202)[0] == []


@pytest.mark.parametrize("retention_case", ["expired_missing", "within_window", "expired_retained"])
async def test_committed_unassociated_replay_respects_retention_without_losing_receipt(
    content_safety_engine,
    content_safety_event,
    content_safety_native_audit,
    content_safety_identities,
    content_safety_clock,
    retention_case,
):
    # AC-39, AC-41, AC-43: a durable receipt survives cleanup, but its replay
    # cannot recreate a deleted old main row. Eligible association repair remains.
    port = ingest_port()
    target_id = str(uuid4())
    raw = content_safety_event(
        forwarded=True,
        backend_request_id=target_id,
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        drain_status="RUNNING",
        conversation=None,
    )
    foreign = content_safety_native_audit(identity=content_safety_identities[1], request_id=target_id)
    with tenant_session(content_safety_engine, 202) as session, session.begin():
        session.add(foreign)
    sessions = SessionPort(content_safety_engine)
    service = port.ContentSafetyIngestService(sessions)
    first = await service.ingest(raw, source(port, raw))
    assert_receipt(first, raw, associated=False)
    original_facts, original_audits = rows(content_safety_engine)
    assert len(original_facts) == 1 and original_audits == []
    original_id, original_hash = original_facts[0].id, original_facts[0].payload_hash
    assert 2 <= len(sessions.sessions) <= 3 and sessions.failed_reads == []
    saved_foreign = rows(content_safety_engine, 202)[1]
    assert len(saved_foreign) == 1 and saved_foreign[0].request_id == target_id
    assert saved_foreign[0].tenant_id == 202 and not saved_foreign[0].has_sensitive_hit

    # Release only the synthetic foreign fixture's global PK, then commit the
    # real retention checkpoint before replaying the already persisted event.
    with tenant_session(content_safety_engine, 202) as session, session.begin():
        session.delete(session.get(DshModelAuditRequest, target_id))
    if retention_case == "expired_retained":
        retained = content_safety_native_audit(
            request_id=target_id,
            model_result="SUCCEEDED",
            response_result="COMPLETED",
            usage_settlement="SETTLED",
        )
        with tenant_session(content_safety_engine) as session, session.begin():
            session.add(retained)
    cutoff = content_safety_clock.now()
    if retention_case != "within_window":
        cutoff += timedelta(seconds=1)
    with tenant_session(content_safety_engine) as session, session.begin():
        setting = DshModelAuditSettingRepository(session).begin_cleanup(before=cutoff)
        assert setting.mode == "OFF" and setting.version == 0

    repeated = await service.ingest(raw, source(port, raw))
    assert_receipt(repeated, raw, duplicate=True, associated=retention_case != "expired_missing")
    facts, audits = rows(content_safety_engine)
    assert len(facts) == 1 and facts[0].id == original_id and facts[0].payload_hash == original_hash
    assert original_hash == wire_hash(raw) and facts[0].stage_results == raw["stage_results"]
    if retention_case == "expired_missing":
        assert audits == []
    else:
        assert len(audits) == 1 and audits[0].request_id == target_id and audits[0].has_sensitive_hit
        assert (audits[0].tenant_id, audits[0].user_id, audits[0].model_id) == (101, 11, 7)
        if retention_case == "expired_retained":
            assert audits[0].record_origin == "MODEL" and audits[0].model_entered is True
            assert audits[0].model_result == "SUCCEEDED" and audits[0].response_result == "COMPLETED"
            assert audits[0].usage_settlement == "SETTLED"
        else:
            assert audits[0].record_origin == "EXTERNAL_SAFETY" and audits[0].effective_mode is None
    assert rows(content_safety_engine, 202) == ([], [])
    assert sessions.failed_reads == []
    assert all(value == (101, None, frozenset({101}), False) for value in sessions.scopes)
