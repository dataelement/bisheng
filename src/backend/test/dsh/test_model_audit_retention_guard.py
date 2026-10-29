"""Coverage AC: AC-41, AC-52, AC-53.

Real native writer and ingest transactions share the setting-before-request gate.
File SQLite and ORM statement/fault observations prove ordering and rollback only;
actual MySQL/DM8 missing-row locking, races and durability remain T119 acceptance.
"""

from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from bisheng.common.errcode.dsh import (
    DshContentSafetyConflictError,
    DshContentSafetyExpiredError,
    DshContentSafetyUnavailableError,
)
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting as Setting
from bisheng.dsh.domain.repositories import content_safety
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository as Settings
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository as WriterRepository
from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent
from bisheng.dsh.domain.services.content_safety_ingest import ContentSafetyIngestService, VerifiedSource
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter
from bisheng.dsh.domain.services.profile import profile_scope
from test.dsh.content_safety_fixtures import safety_database
from test.dsh.model_audit_fixtures import AUDIT_MODELS
from test.dsh.test_content_safety_repository import decoded, tenant_session, wire_hash


@pytest.fixture
def guard_engine(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "retention-guard.sqlite"))
    with safety_database(engine=engine):
        SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in AUDIT_MODELS])
        tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in AUDIT_MODELS)
        yield engine
    engine.dispose()


class Transactions:
    """Observe real caller sessions and inject failures at their actual SQL flush."""

    def __init__(self, engine, *, fault=None):
        self.engine, self.fault = engine, fault
        self.sessions, self.trace = [], []
        self.commits = self.rollbacks = 0

    def __call__(self):
        session = Session(self.engine, expire_on_commit=False)
        self.sessions.append(session)

        def read(state):
            if not state.is_select:
                return
            for table in state.statement.get_final_froms():
                name = getattr(table, "name", "")
                if name in {Setting.__tablename__, Request.__tablename__, Fact.__tablename__}:
                    locked = state.statement._for_update_arg is not None
                    self.trace.append(("read", name, locked, get_current_tenant_id()))
                    if locked:
                        assert state.statement.get_execution_options().get("populate_existing") is True

        def flush(current, _context, _instances):
            if any(isinstance(row, Setting) for row in current.new):
                self.trace.append(("sentinel", Setting.__tablename__, False, get_current_tenant_id()))
                assert not any(isinstance(row, Request) for row in current.new), (
                    "Sentinel must flush before staging a request"
                )
                if self.fault == "flush":
                    raise RuntimeError("synthetic sentinel flush failure")
                if self.fault == "unique":
                    raise IntegrityError("synthetic sentinel unique conflict", {}, RuntimeError("synthetic winner"))

        def commit(_session):
            self.commits += 1

        def rollback(_session):
            self.rollbacks += 1

        event.listen(session, "do_orm_execute", read)
        event.listen(session, "before_flush", flush)
        event.listen(session, "after_commit", commit)
        event.listen(session, "after_rollback", rollback)
        return session

    def writer(self):
        @contextmanager
        def scope():
            with strict_tenant_filter(), self() as session, session.begin():
                yield WriterRepository(session)

        def no_body_storage():
            raise AssertionError("Metadata-only fixture must not access object storage")

        return DshModelAuditWriter(scope, no_body_storage, attempts=1)

    def assert_order(self, *, missing, tenant=101):
        locks = [index for index, item in enumerate(self.trace) if item[:3] == ("read", Setting.__tablename__, True)]
        request_reads = [index for index, item in enumerate(self.trace) if item[:2] == ("read", Request.__tablename__)]
        assert locks, "Admission must lock the tenant retention setting"
        assert request_reads and min(locks) < min(request_reads), "Setting lock must precede every request lookup"
        if missing:
            inserts = [index for index, item in enumerate(self.trace) if item[0] == "sentinel"]
            assert len(inserts) == 1 and min(locks) < inserts[0] < min(request_reads)
        assert all(item[3] == tenant for item in self.trace)


def native(clock, *, tenant=101, request_id=None, started_at=None):
    return AuditEvent(
        request_id=request_id or str(uuid4()),
        tenant_id=tenant,
        kind="entered",
        observed_at=clock.now(),
        metadata={
            "user_id": 11 if tenant == 101 else 22,
            "session_id": None,
            "model_id": 7 if tenant == 101 else 8,
            "conversation_id": None,
            "effective_mode": "METADATA",
            "started_at": started_at or clock.now(),
        },
    )


def checkpoint(engine, cutoff, *, tenant=101, mode="CONTENT", version=7):
    with tenant_session(engine, tenant) as session, session.begin():
        row = Settings(session).lock_retention()
        row.mode, row.version = mode, version
        Settings(session).begin_cleanup(before=cutoff)


def settings(engine, tenant=101):
    with tenant_session(engine, tenant) as session:
        return session.exec(select(Setting)).all()


def counts(engine, tenant=101):
    with tenant_session(engine, tenant) as session:
        return len(session.exec(select(Request)).all()), len(session.exec(select(Fact)).all())


async def ingest(transactions, raw):
    return await ContentSafetyIngestService(transactions).ingest(
        raw, VerifiedSource(raw["source_id"], int(raw["tenant_id"]))
    )


@pytest.mark.parametrize("caller", ["native", "receiver"])
async def test_first_admission_flushes_default_setting_before_request_and_commits_together(
    guard_engine, content_safety_event, content_safety_clock, caller
):
    transactions = Transactions(guard_engine)
    if caller == "native":
        assert await transactions.writer().write(native(content_safety_clock))
    else:
        assert (await ingest(transactions, content_safety_event(conversation=None))).receipt == "COMMITTED"
    transactions.assert_order(missing=True)
    row = settings(guard_engine)[0]
    assert (row.tenant_id, row.mode, row.version, row.updated_by) == (101, "OFF", 0, None)
    assert row.audit_deleted_before is row.cleanup_before is None
    assert counts(guard_engine) == (1, int(caller == "receiver")) and transactions.commits == 1


@pytest.mark.parametrize("caller", ["native", "receiver"])
async def test_existing_setting_is_locked_first_without_mutating_mode_version_or_cutoff(
    guard_engine, content_safety_event, content_safety_clock, caller
):
    cutoff = content_safety_clock.now()
    checkpoint(guard_engine, cutoff)
    transactions = Transactions(guard_engine)
    if caller == "native":
        assert await transactions.writer().write(native(content_safety_clock))
    else:
        assert (await ingest(transactions, content_safety_event(conversation=None))).receipt == "COMMITTED"
    transactions.assert_order(missing=False)
    row = settings(guard_engine)[0]
    assert (row.mode, row.version) == ("CONTENT", 7)
    assert row.audit_deleted_before == row.cleanup_before == cutoff.replace(tzinfo=None)


@pytest.mark.parametrize("caller", ["native", "receiver"])
@pytest.mark.parametrize("fault", ["flush", "unique"])
async def test_default_sentinel_flush_failure_cannot_fall_through_to_request_or_commit(
    guard_engine, content_safety_event, content_safety_clock, caller, fault
):
    transactions = Transactions(guard_engine, fault=fault)
    if caller == "native":
        assert await transactions.writer().write(native(content_safety_clock)) is False
    else:
        with pytest.raises(DshContentSafetyUnavailableError):
            await ingest(transactions, content_safety_event(conversation=None))
    assert transactions.commits == 0 and counts(guard_engine) == (0, 0) and settings(guard_engine) == []
    assert any(item[0] == "sentinel" for item in transactions.trace)
    assert not any(item[1] == Request.__tablename__ for item in transactions.trace)
    assert len(transactions.sessions) == (3 if caller == "receiver" and fault == "unique" else 1)
    assert len({id(session) for session in transactions.sessions}) == len(transactions.sessions)


@pytest.mark.parametrize("caller", ["native", "receiver"])
def test_default_sentinel_and_admission_are_in_callers_rollback_scope(
    guard_engine, content_safety_event, content_safety_clock, caller
):
    transactions = Transactions(guard_engine)
    with pytest.raises(RuntimeError, match="synthetic caller rollback"):
        with profile_scope(101), strict_tenant_filter(), transactions() as session, session.begin():
            if caller == "native":
                WriterRepository(session).upsert_request(native(content_safety_clock))
            else:
                raw = content_safety_event(conversation=None)
                content_safety.append_event(session, decoded(raw), wire_hash(raw))
            rows = session.exec(select(Setting)).all()
            assert len(rows) == 1 and (rows[0].mode, rows[0].version) == ("OFF", 0)
            raise RuntimeError("synthetic caller rollback")
    assert counts(guard_engine) == (0, 0) and settings(guard_engine) == [] and transactions.commits == 0


@pytest.mark.parametrize("caller", ["native", "receiver"])
@pytest.mark.parametrize("delta,allowed", [(-1, False), (0, True), (1, True)])
async def test_missing_request_obeys_strict_watermark_boundary(
    guard_engine, content_safety_clock, content_safety_event, caller, delta, allowed
):
    cutoff = content_safety_clock.now()
    checkpoint(guard_engine, cutoff)
    transactions = Transactions(guard_engine)
    start = cutoff + timedelta(microseconds=delta)
    if caller == "native":
        assert await transactions.writer().write(native(content_safety_clock, started_at=start)) is allowed
    else:
        raw = content_safety_event(request_started_at=start.isoformat(), conversation=None)
        if allowed:
            assert (await ingest(transactions, raw)).receipt == "COMMITTED"
        else:
            with pytest.raises(DshContentSafetyExpiredError):
                await ingest(transactions, raw)
    assert counts(guard_engine) == (int(allowed), int(allowed and caller == "receiver"))
    assert (settings(guard_engine)[0].mode, settings(guard_engine)[0].version) == ("CONTENT", 7)


async def test_native_valid_retained_old_request_can_still_accept_late_control(
    guard_engine, content_safety_clock, content_safety_native_audit
):
    start = content_safety_clock.now() - timedelta(days=2)
    row = content_safety_native_audit(started_at=start, model_started_at=start, session_id=None, conversation_id=None)
    with tenant_session(guard_engine) as session, session.begin():
        session.add(row)
    checkpoint(guard_engine, content_safety_clock.now())
    transactions = Transactions(guard_engine)
    assert await transactions.writer().write(native(content_safety_clock, request_id=row.request_id, started_at=start))
    transactions.assert_order(missing=False)
    assert counts(guard_engine) == (1, 0)


@pytest.mark.parametrize("caller", ["native", "receiver"])
async def test_tenant_watermark_and_missing_default_rows_are_isolated(
    guard_engine, content_safety_clock, content_safety_event, content_safety_identities, caller
):
    cutoff = content_safety_clock.now()
    checkpoint(guard_engine, cutoff)
    start = cutoff - timedelta(days=1)
    for tenant, identity in zip((101, 202), content_safety_identities, strict=True):
        transactions = Transactions(guard_engine)
        if caller == "native":
            assert await transactions.writer().write(native(content_safety_clock, tenant=tenant, started_at=start)) is (
                tenant == 202
            )
        else:
            raw = content_safety_event(identity=identity, request_started_at=start.isoformat(), conversation=None)
            if tenant == 101:
                with pytest.raises(DshContentSafetyExpiredError):
                    await ingest(transactions, raw)
            else:
                assert (await ingest(transactions, raw)).receipt == "COMMITTED"
        assert all(item[3] == tenant for item in transactions.trace)
    assert counts(guard_engine, 101) == (0, 0)
    assert counts(guard_engine, 202) == (1, int(caller == "receiver"))
    other = settings(guard_engine, 202)
    assert len(other) == 1 and (other[0].mode, other[0].version) == ("OFF", 0)
    assert settings(guard_engine, 101)[0].audit_deleted_before == cutoff.replace(tzinfo=None)


@pytest.mark.parametrize("identity_matches", [False, True])
async def test_receiver_old_request_requires_an_existing_valid_identity(
    guard_engine, content_safety_clock, content_safety_event, content_safety_native_audit, identity_matches
):
    start = content_safety_clock.now() - timedelta(days=1)
    row = content_safety_native_audit(started_at=start, user_id=11 if identity_matches else 99)
    with tenant_session(guard_engine) as session, session.begin():
        session.add(row)
    checkpoint(guard_engine, content_safety_clock.now())
    raw = content_safety_event(
        forwarded=True,
        backend_request_id=row.request_id,
        request_started_at=start.isoformat(),
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        drain_status="RUNNING",
        conversation=None,
    )
    transactions = Transactions(guard_engine)
    if identity_matches:
        assert (await ingest(transactions, raw)).receipt == "COMMITTED"
        transactions.assert_order(missing=False)
    else:
        with pytest.raises(DshContentSafetyExpiredError):
            await ingest(transactions, raw)
    assert counts(guard_engine) == (1, int(identity_matches))


@pytest.mark.parametrize("replay", ["identical", "changed-payload", "same-version-other-id"])
def test_saved_receipt_or_conflict_precedes_retention_lock_even_below_new_watermark(
    guard_engine, content_safety_clock, content_safety_event, replay
):
    raw = content_safety_event(conversation=None)
    with tenant_session(guard_engine) as session, session.begin():
        first, _ = content_safety.append_event(session, decoded(raw), wire_hash(raw))
    checkpoint(guard_engine, content_safety_clock.now() + timedelta(days=1))
    incoming = dict(raw)
    if replay == "changed-payload":
        incoming["policy_version"] += 1
    elif replay == "same-version-other-id":
        incoming["event_id"] = str(uuid4())
    transactions = Transactions(guard_engine)
    with profile_scope(101), strict_tenant_filter(), transactions() as session, session.begin():
        if replay == "identical":
            stored, duplicate = content_safety.append_event(session, decoded(incoming), wire_hash(incoming))
            assert duplicate and stored.id == first.id
        else:
            with pytest.raises(DshContentSafetyConflictError):
                content_safety.append_event(session, decoded(incoming), wire_hash(incoming))
    assert not any(item[1] == Setting.__tablename__ for item in transactions.trace)
    assert counts(guard_engine) == (0, 1)
