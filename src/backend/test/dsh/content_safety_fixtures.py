"""F111 opt-in synthetic fixtures; SQLite checks logic, never MySQL/DM8 behavior.

Coverage AC: AC-39, AC-42, AC-53.
Real-store tests may supply an isolated engine to ``safety_database``. No fixture
opens a production database, starts model runtime, or supplies real credentials.
"""

import re
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from bisheng.core.context.tenant import set_current_tenant_id, strict_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode, DshAuditTreePath, DshAuditTreeState

NOW = datetime(2026, 10, 23, 2, tzinfo=UTC)
SAFETY_MODELS = (
    DshContentSafetyEvent,
    DshModelAuditRequest,
    DshModelAuditSetting,
    DshModelAuditConversation,
    DshAuditTreeState,
    DshAuditTreeNode,
    DshAuditTreePath,
)


@dataclass(frozen=True)
class SafetyIdentity:
    tenant_id: int = 101
    user_id: int = 11
    model_id: int = 7
    session_id: str = "10100000-0000-4000-8000-000000000001"


def safety_identities() -> tuple[SafetyIdentity, SafetyIdentity]:
    return SafetyIdentity(), SafetyIdentity(202, 22, 8, "20200000-0000-4000-8000-000000000002")


@dataclass
class SafetyClock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now()


class SafetyFaults:
    """Named, finite faults for commit/ACK/crash-boundary tests."""

    def __init__(self):
        self.pending = Counter()
        self.observed = []

    def fail_next(self, point: str, count: int = 1) -> None:
        if count < 1:
            raise ValueError("Fault count must be positive")
        self.pending[point] += count

    def check(self, point: str) -> None:
        self.observed.append(point)
        if self.pending[point]:
            self.pending[point] -= 1
            raise RuntimeError("Synthetic content-safety fault: " + point)


def safety_event_factory(clock: SafetyClock) -> Callable[..., dict]:
    sequence = 0

    def make(*, identity: SafetyIdentity | None = None, **changes) -> dict:
        nonlocal sequence
        sequence += 1
        actor = identity or SafetyIdentity()
        timestamp = clock.now().isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": 1,
            "source_id": "synthetic-gateway",
            "event_id": str(uuid5(NAMESPACE_URL, f"f111:event:{sequence}")),
            "gateway_request_id": str(uuid5(NAMESPACE_URL, f"f111:request:{sequence}")),
            "backend_request_id": None,
            "tenant_id": str(actor.tenant_id),
            "user_id": str(actor.user_id),
            "model_id": str(actor.model_id),
            "session_id": actor.session_id,
            "protocol": "CHAT",
            "event_kind": "DECISION",
            "event_version": 1,
            "request_started_at": timestamp,
            "occurred_at": timestamp,
            "stage_results": {"input": "BLOCKED", "output": "NOT_APPLICABLE"},
            "stage_versions": {"input": 1, "output": 1},
            "policy_version": 1,
            "builtin_digest": "a" * 64,
            "hit_count": 1,
            "hit_count_truncated": False,
            "rule_refs": ["synthetic-rule-1"],
            "forwarded": False,
            "drain_status": "NOT_REQUIRED",
            "conversation": {
                "conversation_id": "synthetic-conversation",
                "request_kind": "chat",
                "session_origin": "main",
            },
        }
        payload.update(changes)
        return payload

    return make


def native_audit_factory(clock: SafetyClock) -> Callable[..., DshModelAuditRequest]:
    sequence = 0

    def make(*, identity: SafetyIdentity | None = None, **changes) -> DshModelAuditRequest:
        nonlocal sequence
        sequence += 1
        actor = identity or SafetyIdentity()
        values = {
            "request_id": str(uuid5(NAMESPACE_URL, f"f111:native:{sequence}")),
            "tenant_id": actor.tenant_id,
            "user_id": actor.user_id,
            "model_id": actor.model_id,
            "session_id": actor.session_id,
            "started_at": clock.now(),
            "model_name": "synthetic-model",
            "effective_mode": "METADATA",
            "record_origin": "MODEL",
            "model_entered": True,
            "model_started_at": clock.now(),
        }
        values.update(changes)
        return DshModelAuditRequest(**values)

    return make


@contextmanager
def safety_database(*, engine: Engine | None = None, create_schema: bool = True):
    """Isolated schema and event hooks; explicit engines are owned by the caller.

    Real MySQL/DM8 tests must validate an isolated test target before calling.
    Schema creation can be disabled to exercise real migrated schemas.
    """
    owned = engine is None
    if engine is not None and engine.dialect.name != "sqlite":
        database = engine.url.database
        schema = engine.url.query.get("schema")
        if engine.dialect.name == "mysql" and any(
            key.lower() in {"database", "db", "schema"} for key in engine.url.query
        ):
            raise ValueError("External content-safety fixtures reject MySQL schema overrides")
        if engine.dialect.name == "dm":
            if schema is not None and database and schema != database:
                raise ValueError("External content-safety fixtures reject conflicting DM8 schemas")
            database = schema if schema is not None else database
        if (
            engine.dialect.name not in {"mysql", "dm"}
            or not isinstance(database, str)
            or re.fullmatch(r"dsh_test_[a-z0-9_]+", database, flags=re.IGNORECASE) is None
        ):
            raise ValueError("External content-safety fixtures require an isolated MySQL/DM8 dsh_test_ database")
    if engine is None:
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    if create_schema:
        SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in SAFETY_MODELS])
    previous_tables = set(tenant_filter._tenant_aware_tables)
    previous_initialized = tenant_filter._initialized
    with Session() as probe:
        previous_listeners = {name: set(getattr(probe.dispatch, name)) for name in ("do_orm_execute", "before_flush")}
    try:
        tenant_filter.register_tenant_filter_events()
        tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in SAFETY_MODELS)
        yield engine
    finally:
        with Session() as probe:
            for name, previous in previous_listeners.items():
                for listener in set(getattr(probe.dispatch, name)) - previous:
                    event.remove(Session, name, listener)
        tenant_filter._tenant_aware_tables = previous_tables
        tenant_filter._initialized = previous_initialized
        if owned:
            engine.dispose()


def safety_transaction_factory(engine: Engine, faults: SafetyFaults):
    @contextmanager
    def transaction(tenant_id: int = 101):
        token = set_current_tenant_id(tenant_id)
        try:
            with strict_tenant_filter(), Session(engine, expire_on_commit=False) as session:

                def before_commit(_session):
                    faults.check("before_commit")

                event.listen(session, "before_commit", before_commit)
                with session.begin():
                    yield session
        finally:
            token.var.reset(token)

    return transaction
