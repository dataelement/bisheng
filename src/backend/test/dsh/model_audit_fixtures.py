"""Deterministic audit fixtures; no network or application credentials."""

from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from bisheng.core.context.tenant import set_current_tenant_id, strict_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models import model_audit_content, model_audit_request, model_audit_setting
from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.infrastructure.model_audit_body_buffer import AuditBodyBuffer
from bisheng.user.domain.models.user import User

NOW = datetime(2026, 10, 14, tzinfo=UTC)
AUDIT_MODELS = (
    DshModelAuditConversation,
    model_audit_setting.DshModelAuditSetting,
    model_audit_setting.DshModelAuditSettingChange,
    model_audit_request.DshModelAuditRequest,
    model_audit_request.DshModelAuditEvidence,
    model_audit_request.DshModelAuditManifest,
    model_audit_content.DshModelAuditContent,
    model_audit_content.DshModelAuditOccurrence,
    model_audit_content.DshModelAuditBodyAccess,
)


@contextmanager
def audit_database():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in AUDIT_MODELS] + [User.__table__])
    previous_tables = set(tenant_filter._tenant_aware_tables)
    previous_initialized = tenant_filter._initialized
    with Session() as probe:
        listeners = {name: set(getattr(probe.dispatch, name)) for name in ("do_orm_execute", "before_flush")}
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in AUDIT_MODELS)
    try:
        yield engine
    finally:
        engine.dispose()
        with Session() as probe:
            for name, previous in listeners.items():
                for listener in set(getattr(probe.dispatch, name)) - previous:
                    event.remove(Session, name, listener)
        tenant_filter._tenant_aware_tables = previous_tables
        tenant_filter._initialized = previous_initialized


@contextmanager
def audit_session(engine, tenant_id=2):
    token = set_current_tenant_id(tenant_id)
    try:
        with Session(engine, expire_on_commit=False) as session, strict_tenant_filter():
            yield session
    finally:
        token.var.reset(token)


class FaultAuditObjects:
    def __init__(self):
        self.data = {}
        self.failure = False

    async def put(self, key, value):
        if self.failure:
            raise OSError("synthetic object fault")
        self.data[key] = value

    async def get_bounded(self, key, maximum):
        if self.failure:
            raise OSError("synthetic object fault")
        value = self.data[key]
        if len(value) > maximum:
            raise ValueError("synthetic oversized object")
        return value


class ControlledAuditQueue:
    def __init__(self, capacity=1024, drop_sequence=None):
        self.events = []
        self.capacity, self.drop_sequence = capacity, drop_sequence

    def put(self, value):
        if len(self.events) >= self.capacity or (value.kind == "body" and value.sequence == self.drop_sequence):
            return False
        self.events.append(value)
        return True

    def open_body_buffer(self, event):
        return AuditBodyBuffer(self, event)

    @staticmethod
    def reserve(_cost):
        return True

    def submit(self, buffer):
        accepted = True
        for body_event in buffer.events():
            if not self.put(body_event):
                accepted = False
        buffer.fragments.clear()
        return accepted

    def drain(self):
        events, self.events = self.events, []
        return events


class AuditTestClock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value

    def advance(self, seconds):
        from datetime import timedelta

        self.value += timedelta(seconds=seconds)


class AuditActivityFixture:
    def __init__(self):
        self.active = set()
        self.unavailable = False

    def started(self, request_id):
        self.active.add(request_id)

    def finished(self, request_id):
        self.active.discard(request_id)

    def confirmed(self, request_id):
        return not self.unavailable and request_id in self.active
