"""Coverage AC: AC-39, AC-41, AC-43, AC-48, AC-51, AC-52, AC-53.

Real caller-owned transactions exercise maintenance, summaries and ingest guards.
File SQLite and controlled unique-key interleaving verify transaction boundaries,
not MySQL/DM8 concurrent lock behavior. Native-writer admission is a separate pair.
This maintenance boundary removes audit rows and associated safety facts only;
retained body metadata, shared objects, encryption keys and billing are not GC.
"""

import importlib
from contextlib import contextmanager, suppress
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from bisheng.common.errcode.dsh import DshContentSafetyExpiredError, DshOperationConflictError
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditEvidence, DshModelAuditManifest
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting as Setting
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState as State
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.repositories import content_safety, content_safety_projection
from bisheng.dsh.domain.repositories.content_safety_queries import ContentSafetyQueryRepository
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Queries
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository as Settings
from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand
from test.dsh.content_safety_fixtures import SafetyIdentity, safety_database
from test.dsh.model_audit_fixtures import AUDIT_MODELS
from test.dsh.test_content_safety_groups import native, project, summary
from test.dsh.test_content_safety_merge import committed_merge, output_event
from test.dsh.test_content_safety_repository import decoded, tenant_session, wire_hash
from test.dsh.test_content_safety_tree import finish


@pytest.fixture
def retention_engine(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "retention.sqlite"))
    models = (*AUDIT_MODELS, DshModelCall, DshMonthlyUsage)
    with safety_database(engine=engine):
        SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
        tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in models)
        yield engine
    engine.dispose()


def maintenance(session):
    module = importlib.import_module("bisheng.dsh.domain.repositories.content_safety_maintenance")
    return module.ContentSafetyMaintenanceRepository(session)


def seed(engine, make, *, tenant=101, received_at=None, **changes):
    identity = SafetyIdentity() if tenant == 101 else SafetyIdentity(202, 22, 8, "20200000-0000-4000-8000-000000000002")
    if received_at is not None:
        changes.setdefault("request_started_at", (received_at - timedelta(seconds=1)).isoformat())
        changes.setdefault("occurred_at", received_at.isoformat())
    raw = make(identity=identity, **changes)
    fact, row, _duplicate = committed_merge(engine, content_safety_projection, raw, tenant_id=tenant)
    if received_at is not None:
        with tenant_session(engine, tenant) as session, session.begin():
            stored = session.get(Fact, fact.id)
            stored.received_at = received_at
            session.add(stored)
    return raw, row


def counts(engine, tenant=101):
    with tenant_session(engine, tenant) as session:
        return len(session.exec(select(Request)).all()), len(session.exec(select(Fact)).all())


def checkpoint(engine, cutoff, *, tenant=101):
    with tenant_session(engine, tenant) as session, session.begin():
        Settings(session).begin_cleanup(before=cutoff)


def purge(engine, *, tenant=101, **options):
    with tenant_session(engine, tenant) as session, session.begin():
        return maintenance(session).purge_batch(**options)


def complete_cleanup(engine, *, tenant=101, **options):
    totals = {"details_deleted": 0, "audits_deleted": 0}
    for _ in range(30):
        result = purge(engine, tenant=tenant, **options)
        for name in totals:
            totals[name] += result[name]
        if not result["has_more"]:
            return totals
    raise AssertionError("Finite retention fixture did not finish within bounded batches")


def test_default_retention_does_not_delete_historical_details_or_main_summary(
    retention_engine, content_safety_event, content_safety_clock
):
    old = content_safety_clock.now() - timedelta(days=365)
    seed(retention_engine, content_safety_event, received_at=old)
    result = purge(retention_engine)
    assert result["details_deleted"] == result["audits_deleted"] == 0
    assert counts(retention_engine) == (1, 1)


def test_explicit_detail_window_is_received_time_bounded_and_tenant_isolated(
    retention_engine, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    for delta in (-3, -2, -1, 0, 1):
        seed(retention_engine, content_safety_event, received_at=cutoff + timedelta(seconds=delta))
    seed(retention_engine, content_safety_event, tenant=202, received_at=cutoff - timedelta(days=10))
    first = purge(retention_engine, details_before=cutoff, limit=2)
    assert first["details_deleted"] == 2 and first["audits_deleted"] == 0
    complete_cleanup(retention_engine, details_before=cutoff, limit=2)
    assert counts(retention_engine) == (5, 2) and counts(retention_engine, 202) == (1, 1)


def test_purged_details_keep_sensitive_summary_native_axes_and_usage_unchanged(
    retention_engine, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    _raw, row = seed(retention_engine, content_safety_event, received_at=cutoff - timedelta(days=31))
    with tenant_session(retention_engine) as session:
        before = deepcopy(session.get(Request, row.request_id).model_dump())
    assert purge(retention_engine, details_before=cutoff)["details_deleted"] == 1
    with tenant_session(retention_engine) as session:
        current = session.get(Request, row.request_id)
        assert current.model_dump() == before
        details = ContentSafetyQueryRepository(session).request_events(row.request_id)
        assert details["items"] == [] and details["details_status"] == "PURGED"
        assert current.has_sensitive_hit and current.content_safety_state == "BLOCKED"
        assert current.model_result is current.response_result is current.usage_settlement is None


def test_checkpoint_commits_before_any_main_deletion_and_does_not_change_mode_version(
    retention_engine, content_safety_event, content_safety_clock
):
    seed(retention_engine, content_safety_event)
    cutoff = content_safety_clock.now() + timedelta(seconds=1)
    checkpoint(retention_engine, cutoff)
    assert counts(retention_engine) == (1, 1)
    with tenant_session(retention_engine) as session:
        row = session.exec(select(Setting)).one()
        assert row.audit_deleted_before == row.cleanup_before == cutoff.replace(tzinfo=None)
        assert (row.mode, row.version) == ("OFF", 0)
    assert complete_cleanup(retention_engine)["audits_deleted"] == 1
    assert counts(retention_engine) == (0, 0)


def test_uncommitted_checkpoint_rolls_back_and_cannot_authorize_later_cleanup(
    retention_engine, content_safety_event, content_safety_clock
):
    seed(retention_engine, content_safety_event)
    with tenant_session(retention_engine) as session:
        Settings(session).begin_cleanup(before=content_safety_clock.now() + timedelta(seconds=1))
        session.rollback()
    assert purge(retention_engine)["audits_deleted"] == 0
    assert counts(retention_engine) == (1, 1)


def test_purge_transaction_failure_rolls_back_all_deletes_but_keeps_committed_watermark(
    retention_engine, content_safety_event, content_safety_clock
):
    seed(retention_engine, content_safety_event)
    cutoff = content_safety_clock.now() + timedelta(seconds=1)
    checkpoint(retention_engine, cutoff)
    with pytest.raises(RuntimeError, match="synthetic after purge"):
        with tenant_session(retention_engine) as session, session.begin():
            maintenance(session).purge_batch()
            session.flush()
            raise RuntimeError("synthetic after purge")
    assert counts(retention_engine) == (1, 1)
    with tenant_session(retention_engine) as session:
        assert session.exec(select(Setting)).one().audit_deleted_before == cutoff.replace(tzinfo=None)
    assert complete_cleanup(retention_engine)["audits_deleted"] == 1


@pytest.mark.parametrize(
    "axis,pending", [("model_result", "RUNNING"), ("response_result", "RUNNING"), ("usage_settlement", "PENDING")]
)
def test_running_or_unsettled_native_row_is_retained_then_revisited_after_it_finishes(
    retention_engine, content_safety_native_audit, content_safety_clock, axis, pending
):
    row = native(content_safety_native_audit, **{axis: pending})
    with tenant_session(retention_engine) as session, session.begin():
        session.add(row)
    checkpoint(retention_engine, content_safety_clock.now() + timedelta(seconds=1))
    assert complete_cleanup(retention_engine)["audits_deleted"] == 0
    assert counts(retention_engine) == (1, 0)
    with tenant_session(retention_engine) as session, session.begin():
        current = session.get(Request, row.request_id)
        setattr(
            current,
            axis,
            "SETTLED" if axis == "usage_settlement" else "COMPLETED" if axis == "response_result" else "SUCCEEDED",
        )
        session.add(current)
    assert complete_cleanup(retention_engine)["audits_deleted"] == 1
    assert counts(retention_engine) == (0, 0)


def test_main_cleanup_uses_strict_started_boundary_and_small_batches(
    retention_engine, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    for delta in (-3, -2, -1, 0, 1):
        at = (cutoff + timedelta(seconds=delta)).isoformat()
        seed(retention_engine, content_safety_event, request_started_at=at, occurred_at=at)
    seed(retention_engine, content_safety_event, tenant=202)
    checkpoint(retention_engine, cutoff)
    first = purge(retention_engine, limit=2)
    assert first["audits_deleted"] == 2
    complete_cleanup(retention_engine, limit=2)
    assert counts(retention_engine) == (2, 2) and counts(retention_engine, 202) == (1, 1)


def test_old_retained_running_main_can_still_receive_late_safety_fact(
    retention_engine, content_safety_native_audit, content_safety_event, content_safety_clock
):
    row = native(
        content_safety_native_audit, model_result="RUNNING", response_result="RUNNING", usage_settlement="PENDING"
    )
    with tenant_session(retention_engine) as session, session.begin():
        session.add(row)
    checkpoint(retention_engine, content_safety_clock.now() + timedelta(seconds=1))
    complete_cleanup(retention_engine)
    raw = output_event(content_safety_event, backend_request_id=row.request_id)
    _fact, merged, _duplicate = committed_merge(retention_engine, content_safety_projection, raw)
    assert merged.request_id == row.request_id and merged.output_sensitive_hit
    assert counts(retention_engine) == (1, 1)


def test_deleted_main_rejects_expired_replay_410_without_deleting_unassociated_facts(
    retention_engine, content_safety_event, content_safety_clock
):
    raw, _row = seed(retention_engine, content_safety_event)
    orphan = output_event(content_safety_event, backend_request_id=None)
    committed_merge(retention_engine, content_safety_projection, orphan)
    checkpoint(retention_engine, content_safety_clock.now() + timedelta(seconds=1))
    complete_cleanup(retention_engine)
    assert counts(retention_engine) == (0, 1)
    with tenant_session(retention_engine) as session, session.begin():
        with pytest.raises(DshContentSafetyExpiredError) as rejected:
            content_safety.append_event(session, decoded(raw), wire_hash(raw))
        assert rejected.value.HttpStatus == 410
    assert counts(retention_engine) == (0, 1)


def test_cleanup_reduces_already_indexed_group_counts_and_dirties_published_safety_tree(
    retention_engine, content_safety_event, content_safety_clock
):
    _raw, row = seed(retention_engine, content_safety_event)
    assert project(retention_engine, row.request_id)
    finish(retention_engine, content_safety_clock.now())
    assert summary(retention_engine, row.conversation_key) == (1, 0, 1, True)
    checkpoint(retention_engine, content_safety_clock.now() + timedelta(seconds=1))
    complete_cleanup(retention_engine)
    group = summary(retention_engine, row.conversation_key)
    assert group is None or group == (0, 0, 0, False)
    with tenant_session(retention_engine) as session:
        assert Queries(session).tree_progress()["summary_ready"] is False
    finish(retention_engine, content_safety_clock.now())
    with tenant_session(retention_engine) as session:
        state = session.get(State, 101)
        nodes = Queries(session).tree_page()["items"]
        assert state.safety_summary_revision == state.published_safety_summary_revision
        assert all(item["branch_summary"]["sensitive_hit_count"] == 0 for item in nodes)


def test_mode_change_and_cleanup_use_fresh_locked_values_without_overwriting_each_other(
    retention_engine, content_safety_clock
):
    with tenant_session(retention_engine) as session, session.begin():
        Settings(session).change(
            AuditModeCommand(operation_id=str(uuid4()), expected_version=0, mode="METADATA"), actor_user_id=11
        )
    cutoff = content_safety_clock.now()
    with tenant_session(retention_engine) as stale:
        stale_row = stale.exec(select(Setting)).one()
        assert stale_row.version == 1
        checkpoint(retention_engine, cutoff)
        Settings(stale).change(
            AuditModeCommand(operation_id=str(uuid4()), expected_version=1, mode="CONTENT"),
            actor_user_id=11,
            content_available=True,
        )
        stale.commit()
    with tenant_session(retention_engine) as stale:
        stale_row = stale.exec(select(Setting)).one()
        assert stale_row.version == 2
        with tenant_session(retention_engine) as writer, writer.begin():
            Settings(writer).change(
                AuditModeCommand(operation_id=str(uuid4()), expected_version=2, mode="OFF"), actor_user_id=11
            )
        Settings(stale).begin_cleanup(before=cutoff + timedelta(days=1))
        stale.commit()
    with tenant_session(retention_engine) as session:
        row = session.exec(select(Setting)).one()
        assert (row.mode, row.version) == ("OFF", 3)
        assert row.audit_deleted_before == row.cleanup_before == (cutoff + timedelta(days=1)).replace(tzinfo=None)
    # A no-op or typed rejection may refuse a backward cutoff; neither may regress it.
    with suppress(ValueError, DshOperationConflictError):
        checkpoint(retention_engine, cutoff)
    with tenant_session(retention_engine) as session:
        assert session.exec(select(Setting)).one().audit_deleted_before == (cutoff + timedelta(days=1)).replace(
            tzinfo=None
        )


def test_retention_lock_creates_missing_default_setting_without_committing_caller_transaction(retention_engine):
    with tenant_session(retention_engine) as session:
        row = Settings(session).lock_retention()
        session.flush()
        assert row.tenant_id == 101 and (row.mode, row.version) == ("OFF", 0)
        assert row.audit_deleted_before is row.cleanup_before is None
        with tenant_session(retention_engine) as observer:
            assert observer.exec(select(Setting)).all() == []
        session.rollback()
    with tenant_session(retention_engine) as session:
        assert session.exec(select(Setting)).all() == []


def test_retention_lock_preserves_existing_mode_version_and_watermark(retention_engine, content_safety_clock):
    cutoff = content_safety_clock.now()
    with tenant_session(retention_engine) as session, session.begin():
        session.add(Setting(mode="CONTENT", version=9, audit_deleted_before=cutoff, cleanup_before=cutoff))
    with tenant_session(retention_engine) as session, session.begin():
        row = Settings(session).lock_retention()
        assert (row.mode, row.version) == ("CONTENT", 9)
        assert row.audit_deleted_before == row.cleanup_before == cutoff.replace(tzinfo=None)


@contextmanager
def first_setting_race(engine):
    competed = []

    def insert_winner(_connection, _cursor, statement, _parameters, _context, _many):
        if not competed and statement.lower().startswith("insert into dsh_model_audit_setting "):
            competed.append(True)
            with engine.begin() as connection:
                connection.execute(
                    insert(Setting.__table__).values(id=str(uuid4()), tenant_id=101, mode="CONTENT", version=7)
                )

    event.listen(engine, "before_cursor_execute", insert_winner)
    try:
        yield competed
    finally:
        event.remove(engine, "before_cursor_execute", insert_winner)


def test_setting_race_fixture_really_commits_a_competing_unique_row(retention_engine):
    with first_setting_race(retention_engine) as competed, pytest.raises(IntegrityError):
        with tenant_session(retention_engine) as session, session.begin():
            session.add(Setting())
            session.flush()
    assert competed
    with tenant_session(retention_engine) as session:
        winner = session.exec(select(Setting)).one()
        assert (winner.mode, winner.version) == ("CONTENT", 7)


def test_first_setting_unique_race_escapes_and_fresh_transaction_preserves_winner_values(
    retention_engine, content_safety_clock
):
    with first_setting_race(retention_engine) as competed, pytest.raises(IntegrityError):
        with tenant_session(retention_engine) as session, session.begin():
            Settings(session).lock_retention()
    assert competed
    checkpoint(retention_engine, content_safety_clock.now())
    with tenant_session(retention_engine) as session:
        row = session.exec(select(Setting)).one()
        assert (row.mode, row.version) == ("CONTENT", 7)
        assert row.audit_deleted_before == content_safety_clock.now().replace(tzinfo=None)


def test_main_cleanup_never_modifies_billing_or_claims_body_metadata_is_reclaimed(
    retention_engine, content_safety_event, content_safety_native_audit, content_safety_clock
):
    row = native(content_safety_native_audit, usage_settlement="UNKNOWN")
    with tenant_session(retention_engine) as session, session.begin():
        session.add(row)
    committed_merge(
        retention_engine,
        content_safety_projection,
        output_event(content_safety_event, backend_request_id=row.request_id),
    )
    with tenant_session(retention_engine) as session, session.begin():
        session.add(
            DshModelCall(
                request_id=row.request_id,
                user_id=11,
                model_id=7,
                session_id=str(uuid4()),
                usage_month="2026-10",
                policy_version=1,
                event_version=1,
                quota_epoch=1,
                status="USAGE_UNKNOWN",
            )
        )
        session.add(
            DshMonthlyUsage(
                user_id=11, model_id=7, usage_month="2026-10", billing_timezone="UTC", used_tokens=73, version=9
            )
        )
        session.add(DshModelAuditManifest(request_id=row.request_id, observed_at=content_safety_clock.now()))
        session.add(DshModelAuditEvidence(request_id=row.request_id, observed_at=content_safety_clock.now()))
    checkpoint(retention_engine, content_safety_clock.now() + timedelta(seconds=1))
    complete_cleanup(retention_engine)
    with tenant_session(retention_engine) as session:
        call = session.get(DshModelCall, row.request_id)
        usage = session.exec(select(DshMonthlyUsage)).one()
        assert call.status == "USAGE_UNKNOWN" and call.total_tokens is None
        assert (usage.used_tokens, usage.version) == (73, 9)
        assert session.get(DshModelAuditManifest, row.request_id) is not None
        assert len(session.exec(select(DshModelAuditEvidence)).all()) == 1


def test_bounded_rebuild_replays_existing_facts_once_without_cross_tenant_or_double_count(
    retention_engine, content_safety_event
):
    rows = [seed(retention_engine, content_safety_event)[1] for _ in range(3)]
    seed(retention_engine, content_safety_event, tenant=202)
    with tenant_session(retention_engine) as session, session.begin():
        for row in session.exec(select(Request)).all():
            row.has_sensitive_hit = row.input_sensitive_hit = False
            row.content_safety_state = row.input_safety_state = row.output_safety_state = "UNREPORTED"
            row.input_safety_version = row.output_safety_version = 0
            session.add(row)
    cursor, examined, seen = None, 0, set()
    for _ in range(10):
        with tenant_session(retention_engine) as session, session.begin():
            result = maintenance(session).rebuild_batch(cursor=cursor, limit=1)
        assert 0 <= result["examined"] <= 1
        examined += result["examined"]
        cursor = result["next_cursor"]
        if cursor is None:
            break
        assert cursor not in seen
        seen.add(cursor)
    else:
        raise AssertionError("Finite rebuild did not advance its bounded cursor")
    assert examined == 3
    for row in rows:
        assert project(retention_engine, row.request_id)
    assert summary(retention_engine, rows[0].conversation_key) == (3, 0, 3, True)
    with tenant_session(retention_engine) as session, session.begin():
        maintenance(session).rebuild_batch()
    for row in rows:
        project(retention_engine, row.request_id)
    assert summary(retention_engine, rows[0].conversation_key) == (3, 0, 3, True)
    assert counts(retention_engine, 202) == (1, 1)


def test_purged_facts_cannot_be_rebuilt_or_reset_retained_sensitive_summary(
    retention_engine, content_safety_event, content_safety_clock
):
    _raw, row = seed(
        retention_engine, content_safety_event, received_at=content_safety_clock.now() - timedelta(days=31)
    )
    purge(retention_engine, details_before=content_safety_clock.now())
    with tenant_session(retention_engine) as session, session.begin():
        assert maintenance(session).rebuild_batch()["examined"] == 0
        assert session.get(Request, row.request_id).has_sensitive_hit
        assert ContentSafetyQueryRepository(session).request_events(row.request_id)["details_status"] == "PURGED"


def test_maintenance_locks_setting_first_and_all_bulk_writes_are_tenant_guarded(
    retention_engine, content_safety_event, content_safety_clock
):
    seed(retention_engine, content_safety_event)
    checkpoint(retention_engine, content_safety_clock.now() + timedelta(seconds=1))
    statements, bulk_writes = [], []

    def capture(_connection, clause, _multiparams, _params, _options):
        statements.append(" ".join(str(clause).lower().split()))

    def capture_bulk(execution):
        if execution.is_update or execution.is_delete:
            bulk_writes.append(" ".join(str(execution.statement).lower().split()))

    event.listen(retention_engine, "before_execute", capture)
    event.listen(Session, "do_orm_execute", capture_bulk)
    try:
        purge(retention_engine)
    finally:
        event.remove(Session, "do_orm_execute", capture_bulk)
        event.remove(retention_engine, "before_execute", capture)
    locks = [sql for sql in statements if sql.startswith("select") and "for update" in sql]
    assert locks and "dsh_model_audit_setting" in locks[0]
    assert any(sql.startswith("delete ") for sql in statements)
    for sql in bulk_writes:
        where = sql.split(" where ", 1)[-1]
        assert "tenant_id" in where
        assert "request_id" in where or ".id" in where or "cleanup_" in where


@pytest.mark.parametrize("limit", [0, -1, True, "1"])
def test_maintenance_rejects_invalid_batch_limits(retention_engine, limit):
    with tenant_session(retention_engine) as session, session.begin():
        repository = maintenance(session)
        with pytest.raises(ValueError):
            repository.purge_batch(limit=limit)
        with pytest.raises(ValueError):
            repository.rebuild_batch(limit=limit)


def test_details_only_does_not_consume_existing_main_cleanup_checkpoint(
    retention_engine, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    _raw, audit = seed(retention_engine, content_safety_event, received_at=cutoff - timedelta(days=31))
    seed(retention_engine, content_safety_event, tenant=202, received_at=cutoff - timedelta(days=31))
    checkpoint(retention_engine, cutoff)
    with tenant_session(retention_engine) as session:
        before = session.exec(select(Setting)).one().model_dump()
    result = purge(retention_engine, details_before=cutoff, include_audits=False)
    assert result == {"details_deleted": 1, "audits_deleted": 0, "has_more": False}
    assert counts(retention_engine) == (1, 0) and counts(retention_engine, 202) == (1, 1)
    with tenant_session(retention_engine) as session:
        assert session.exec(select(Setting)).one().model_dump() == before
        assert session.get(Request, audit.request_id).has_sensitive_hit
        assert ContentSafetyQueryRepository(session).request_events(audit.request_id)["details_status"] == "PURGED"
    assert complete_cleanup(retention_engine)["audits_deleted"] == 1
    assert counts(retention_engine) == (0, 0)
