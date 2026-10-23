"""Coverage AC: AC-38, AC-39, AC-41, AC-42, AC-51, AC-53.

Repository ports use real isolated SQLAlchemy sessions. SQLite verifies transaction
control and uniqueness paths only, not MySQL/DM8 concurrency or durability.
"""

import hashlib
import importlib
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshContentSafetyConflictError, DshContentSafetyExpiredError
from bisheng.core.context.tenant import set_current_tenant_id, strict_tenant_filter, visible_tenant_ids
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent
from test.dsh.content_safety_fixtures import safety_database


def repository_port():
    return importlib.import_module("bisheng.dsh.domain.repositories.content_safety")


def wire_hash(payload):
    """Supply the caller's canonical digest of the original wire event as fixture data."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def decoded(payload):
    return ContentSafetyEvent.model_validate(payload)


@contextmanager
def tenant_session(engine, tenant_id=101):
    token = set_current_tenant_id(tenant_id)
    try:
        with strict_tenant_filter(), Session(engine, expire_on_commit=False) as session:
            yield session
    finally:
        token.var.reset(token)


def committed_append(repository, engine, payload, *, tenant_id=101):
    with tenant_session(engine, tenant_id) as session, session.begin():
        row, duplicate = repository.append_event(session, decoded(payload), wire_hash(payload))
    return row, duplicate


def test_first_event_and_identical_replay_have_one_committed_fact(content_safety_engine, content_safety_event):
    repository = repository_port()
    raw = content_safety_event()
    row, duplicate = committed_append(repository, content_safety_engine, raw)
    assert isinstance(row, DshContentSafetyEvent)
    assert not duplicate and row.payload_hash == wire_hash(raw)
    repeated, duplicate = committed_append(repository, content_safety_engine, raw)
    assert duplicate and repeated.id == row.id
    assert repeated.association_status == "UNASSOCIATED" and repeated.audit_request_id is None
    with tenant_session(content_safety_engine) as session:
        receipt = repository.lookup_receipt(session, decoded(raw), wire_hash(raw))
        assert receipt.id == row.id
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


def test_canonical_key_order_does_not_change_replay_identity(content_safety_engine, content_safety_event):
    repository = repository_port()
    raw = content_safety_event()
    ordered_differently = dict(reversed(list(raw.items())))
    ordered_differently["stage_results"] = dict(reversed(list(raw["stage_results"].items())))
    assert wire_hash(raw) == wire_hash(ordered_differently)
    first, _ = committed_append(repository, content_safety_engine, raw)
    second, duplicate = committed_append(repository, content_safety_engine, ordered_differently)
    assert duplicate and first.id == second.id


@pytest.mark.parametrize("optional_field", ["backend_request_id", "session_id", "conversation"])
def test_missing_optional_field_and_explicit_null_are_distinct_original_facts(
    content_safety_engine, content_safety_event, optional_field
):
    repository = repository_port()
    missing = content_safety_event()
    missing.pop(optional_field)
    explicit_null = {**missing, optional_field: None}
    # DTO defaults must not replace the original wire representation for hashing.
    assert decoded(missing).model_dump() == decoded(explicit_null).model_dump()
    assert wire_hash(missing) != wire_hash(explicit_null)
    original, _ = committed_append(repository, content_safety_engine, missing)
    with tenant_session(content_safety_engine) as session, session.begin():
        with pytest.raises(DshContentSafetyConflictError):
            repository.append_event(session, decoded(explicit_null), wire_hash(explicit_null))
    with tenant_session(content_safety_engine) as session:
        stored = repository.lookup_receipt(session, decoded(missing), wire_hash(missing))
        assert stored.id == original.id and stored.payload_hash == wire_hash(missing)
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


def test_same_source_event_id_changed_payload_is_conflict_without_overwrite(
    content_safety_engine, content_safety_event
):
    repository = repository_port()
    raw = content_safety_event()
    original, _ = committed_append(repository, content_safety_engine, raw)
    changed = {**raw, "hit_count": raw["hit_count"] + 1}
    with tenant_session(content_safety_engine) as session, session.begin():
        with pytest.raises(DshContentSafetyConflictError):
            repository.append_event(session, decoded(changed), wire_hash(changed))
    with tenant_session(content_safety_engine) as session:
        stored = repository.lookup_receipt(session, decoded(raw), wire_hash(raw))
        assert stored.id == original.id and stored.hit_count == raw["hit_count"]
        with pytest.raises(DshContentSafetyConflictError):
            repository.lookup_receipt(session, decoded(changed), wire_hash(changed))


def test_same_request_version_with_another_event_and_facts_is_conflict(content_safety_engine, content_safety_event):
    repository = repository_port()
    raw = content_safety_event()
    committed_append(repository, content_safety_engine, raw)
    other = {**raw, "event_id": str(uuid4()), "hit_count": raw["hit_count"] + 1}
    with tenant_session(content_safety_engine) as session, session.begin():
        with pytest.raises(DshContentSafetyConflictError):
            repository.append_event(session, decoded(other), wire_hash(other))
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


def test_event_deduplication_is_scoped_by_source(content_safety_engine, content_safety_event):
    repository = repository_port()
    raw = content_safety_event()
    first, _ = committed_append(repository, content_safety_engine, raw)
    other = {**raw, "source_id": "another-synthetic-gateway"}
    second, duplicate = committed_append(repository, content_safety_engine, other)
    assert not duplicate and first.id != second.id
    assert first.event_id == second.event_id
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 2


def test_strict_tenant_lookup_does_not_inherit_visible_parent_scope(content_safety_engine, content_safety_event):
    repository = repository_port()
    raw = content_safety_event()
    committed_append(repository, content_safety_engine, raw)
    other_tenant = {**raw, "tenant_id": "202", "user_id": "22", "model_id": "8"}
    tenant_token = set_current_tenant_id(202)
    visible_token = visible_tenant_ids.set(frozenset({101, 202}))
    try:
        # The repository itself must enforce strict scope, independent of callers.
        with Session(content_safety_engine) as session:
            assert repository.lookup_receipt(session, decoded(other_tenant), wire_hash(other_tenant)) is None
    finally:
        visible_tenant_ids.reset(visible_token)
        tenant_token.var.reset(tenant_token)


def test_newer_trusted_identity_is_accepted_without_freezing_request_owner(
    content_safety_engine, content_safety_event, content_safety_identities
):
    repository = repository_port()
    raw = content_safety_event()
    first, _ = committed_append(repository, content_safety_engine, raw)
    changed_identity = content_safety_event(
        identity=content_safety_identities[1], gateway_request_id=raw["gateway_request_id"], event_version=2
    )
    second, duplicate = committed_append(repository, content_safety_engine, changed_identity, tenant_id=202)
    assert not duplicate and (second.tenant_id, second.user_id, second.model_id) == (202, 22, 8)
    assert first.gateway_request_id == second.gateway_request_id
    old_retry, duplicate = committed_append(repository, content_safety_engine, raw)
    assert duplicate and old_retry.id == first.id
    with tenant_session(content_safety_engine, 202) as session:
        records = session.exec(select(DshContentSafetyEvent)).all()
        assert len(records) == 1 and records[0].id == second.id


def test_append_never_commits_and_caller_rollback_removes_fact_and_summary(
    content_safety_engine, content_safety_event, content_safety_native_audit
):
    repository = repository_port()
    raw = content_safety_event()
    commits = []
    with tenant_session(content_safety_engine) as session:
        event.listen(session, "after_commit", lambda _: commits.append(True))
        with pytest.raises(RuntimeError, match="synthetic caller rollback"):
            with session.begin():
                repository.append_event(session, decoded(raw), wire_hash(raw))
                session.add(content_safety_native_audit(request_id=raw["gateway_request_id"]))
                session.flush()
                assert not commits
                raise RuntimeError("synthetic caller rollback")
        assert not commits
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshContentSafetyEvent)).all() == []
        assert session.get(DshModelAuditRequest, raw["gateway_request_id"]) is None


def test_unique_insert_race_is_re_read_only_after_failed_transaction_exits(tmp_path, content_safety_event):
    repository = repository_port()
    raw = content_safety_event()
    engine = create_engine("sqlite:///" + str(tmp_path / "unique-race.sqlite"), connect_args={"timeout": 2})
    winner_ids = []
    raced = False
    try:
        with safety_database(engine=engine):
            # Keep this race focused on Fact uniqueness; first-setting admission
            # has its own real transaction/failure tests in T168.
            with tenant_session(engine) as initial, initial.begin():
                initial.add(DshModelAuditSetting())

            def insert_winner_before_loser(_connection, _cursor, _statement, _parameters, context, _many):
                nonlocal raced
                if raced or not context.isinsert or context.compiled.statement.table.name != "dsh_content_safety_event":
                    return
                raced = True
                winner, duplicate = committed_append(repository, engine, raw)
                assert not duplicate
                winner_ids.append(winner.id)

            event.listen(engine, "before_cursor_execute", insert_winner_before_loser)
            try:
                with tenant_session(engine) as loser:
                    with pytest.raises(IntegrityError):
                        with loser.begin():
                            repository.append_event(loser, decoded(raw), wire_hash(raw))
                    assert loser.is_active
                assert raced and len(winner_ids) == 1
                # This is a fresh session and transaction, not a failed-session query.
                with tenant_session(engine) as recovery, recovery.begin():
                    receipt = repository.lookup_receipt(recovery, decoded(raw), wire_hash(raw))
                    assert receipt.id == winner_ids[0]
                    row, duplicate = repository.append_event(recovery, decoded(raw), wire_hash(raw))
                    assert duplicate and row.id == receipt.id
                    assert len(recovery.exec(select(DshContentSafetyEvent)).all()) == 1
            finally:
                event.remove(engine, "before_cursor_execute", insert_winner_before_loser)
    finally:
        engine.dispose()


def test_deleted_main_request_cannot_be_resurrected_by_old_event(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_clock
):
    repository = repository_port()
    start = content_safety_clock.now() - timedelta(hours=2)
    watermark = content_safety_clock.now() - timedelta(hours=1)
    request_id = str(uuid4())
    raw = content_safety_event(
        backend_request_id=request_id, request_started_at=start.isoformat().replace("+00:00", "Z")
    )
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(content_safety_native_audit(request_id=request_id, started_at=start))
    with tenant_session(content_safety_engine) as session, session.begin():
        session.delete(session.get(DshModelAuditRequest, request_id))
        session.add(DshModelAuditSetting(audit_deleted_before=watermark))
    with tenant_session(content_safety_engine) as session, session.begin():
        with pytest.raises(DshContentSafetyExpiredError) as error:
            repository.append_event(session, decoded(raw), wire_hash(raw))
        assert error.value.HttpStatus == 410 and error.value.code == 26173
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshContentSafetyEvent)).all() == []
        assert session.get(DshModelAuditRequest, request_id) is None


def test_existing_valid_old_main_request_still_accepts_late_fact(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_clock
):
    repository = repository_port()
    start = content_safety_clock.now() - timedelta(hours=2)
    watermark = content_safety_clock.now() - timedelta(hours=1)
    request_id = str(uuid4())
    raw = content_safety_event(
        backend_request_id=request_id, request_started_at=start.isoformat().replace("+00:00", "Z")
    )
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(content_safety_native_audit(request_id=request_id, started_at=start))
        session.add(DshModelAuditSetting(audit_deleted_before=watermark))
    row, duplicate = committed_append(repository, content_safety_engine, raw)
    assert not duplicate and row.backend_request_id == request_id


def test_existing_committed_event_replay_precedes_newer_retention_watermark(
    content_safety_engine, content_safety_event, content_safety_clock
):
    repository = repository_port()
    raw = content_safety_event()
    first, _ = committed_append(repository, content_safety_engine, raw)
    with tenant_session(content_safety_engine) as session, session.begin():
        setting = session.exec(select(DshModelAuditSetting)).one()
        setting.audit_deleted_before = content_safety_clock.now() + timedelta(hours=1)
        session.add(setting)
    repeated, duplicate = committed_append(repository, content_safety_engine, raw)
    assert duplicate and repeated.id == first.id
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshModelAuditRequest)).all() == []
        assert len(session.exec(select(DshContentSafetyEvent)).all()) == 1


@pytest.mark.parametrize("delta,expired", [(-1, True), (0, False), (1, False)])
def test_retention_boundary_is_strictly_before_and_not_equal(
    content_safety_engine, content_safety_event, content_safety_clock, delta, expired
):
    repository = repository_port()
    watermark = content_safety_clock.now()
    start = watermark + timedelta(seconds=delta)
    raw = content_safety_event(request_started_at=start.isoformat().replace("+00:00", "Z"))
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(DshModelAuditSetting(audit_deleted_before=watermark))
    with tenant_session(content_safety_engine) as session:
        if expired:
            with pytest.raises(DshContentSafetyExpiredError):
                repository.retention_guard(session, decoded(raw))
        else:
            assert repository.retention_guard(session, decoded(raw)) is None


def test_retention_defaults_allow_historical_fact_without_setting_watermark(
    content_safety_engine, content_safety_event, content_safety_clock
):
    repository = repository_port()
    raw = content_safety_event(
        request_started_at=(content_safety_clock.now() - timedelta(days=365)).isoformat().replace("+00:00", "Z")
    )
    before = deepcopy(raw)
    with tenant_session(content_safety_engine) as session:
        assert repository.retention_guard(session, decoded(raw)) is None
        setting = session.exec(select(DshModelAuditSetting)).one()
        assert (setting.mode, setting.version, setting.audit_deleted_before) == ("OFF", 0, None)
    with tenant_session(content_safety_engine) as session:
        assert session.exec(select(DshModelAuditSetting)).all() == [], "The caller did not commit its default lock row"
    assert raw == before
