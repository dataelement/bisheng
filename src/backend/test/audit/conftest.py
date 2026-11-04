"""Shared fixtures for the F056 audit query-face tests (``test/audit/``).

Same strategy as ``test_audit_log_tenant_scope.py``: a self-contained SQLite
engine + ``Session`` bound into ``AuditLogDao`` by monkeypatching the module's
``get_sync_db_session`` / ``bypass_tenant_filter``, so the real DAO body runs
against the real predicates without the service stack. The older files keep
their own private copies of these fixtures; new files use the ones here.

Two things the fixtures pin down that are easy to get wrong:

* ``_db_dialect`` is patched to ``sqlite``. Without a live connection the
  helper falls back to ``mysql`` and the JSON predicates compile to
  ``JSON_EXTRACT`` / ``JSON_CONTAINS``, which SQLite does not have.
* The async DAO lookups the service does for enrichment (``AppDao`` /
  ``TenantDao`` / ``UserDao`` / ``UserGroupDao``) are replaced by
  ``AsyncMock`` s the test controls, so a test states exactly which
  applications / tenants / owners exist instead of standing up four tables.
"""

# Pre-mock the modules audit_log eagerly imports that aren't available in the
# unit-test environment (see test_audit_log_tenant_scope.py for the why).
#
# ⚠️ The stubs are **taken back out as soon as our own imports are done**. A
# conftest is loaded at session start — before any test module — so a stub left
# in ``sys.modules`` is not scoped to this directory: it becomes the answer
# every later suite gets. ``bisheng.telemetry_search`` is a real package, and a
# MagicMock standing in for it makes ``import bisheng.telemetry_search.domain``
# fail with "not a package" — which is how ``test/open_api`` and
# ``test/permission`` turned into 11 collection errors the first time this
# block lived in a conftest instead of a test module.
import sys as _sys
from unittest.mock import MagicMock as _MagicMock

_router_stub = _MagicMock()
_router_stub.router = _MagicMock()
_router_stub.router_rpc = _MagicMock()
_stubbed: list[str] = []
for _m in (
    "bisheng.api.router",
    "bisheng.api.v1",
    "bisheng.api.v1.assistant",
    "bisheng.api.v1.schema",
    "bisheng.api.v1.schema.chat_schema",
    "bisheng.api.v1.schema.workflow",
    "bisheng.api.v1.schemas",
    "bisheng.telemetry_search",
    "bisheng.telemetry_search.api",
    "bisheng.telemetry_search.api.router",
):
    if _m not in _sys.modules:
        _sys.modules[_m] = _router_stub
        _stubbed.append(_m)

from contextlib import asynccontextmanager, contextmanager, nullcontext  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402

from bisheng.database.models.audit_log import AuditLog  # noqa: E402

for _m in _stubbed:
    del _sys.modules[_m]
del _stubbed

AUDITLOG_DDL = """
    CREATE TABLE IF NOT EXISTS auditlog (
        id VARCHAR(255) PRIMARY KEY,
        operator_id INTEGER NOT NULL,
        operator_name VARCHAR(255),
        group_ids JSON,
        system_id VARCHAR(64),
        event_type VARCHAR(64),
        object_type VARCHAR(64),
        object_id VARCHAR(64),
        object_name TEXT,
        note TEXT,
        ip_address VARCHAR(64),
        tenant_id INTEGER,
        operator_tenant_id INTEGER,
        action VARCHAR(64),
        target_type VARCHAR(32),
        target_id VARCHAR(64),
        reason TEXT,
        metadata JSON,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
"""


@pytest.fixture(autouse=True)
def _tenant_context():
    """Give every test in this directory its own tenant context.

    These tests drive the DAO's hand-written predicates against a private
    SQLite engine, but the tenant-filter listener is registered on the Session
    class globally: with ``multi_tenant.enabled`` on and no context set, the
    very first INSERT raises ``NoTenantContextError``. Whether the flag is on
    depends on what ran before — ``test/permission`` turns it on and does not
    put it back — so the suite passed alone and failed in a combined run, which
    is exactly the failure the AGENTS.md baseline-diff rule warns about. Pinning
    a context here makes the outcome the same either way.
    """
    from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id

    previous = get_current_tenant_id()
    set_current_tenant_id(1)
    try:
        yield
    finally:
        set_current_tenant_id(previous)


@pytest.fixture(scope="module")
def audit_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text(AUDITLOG_DDL))
    yield engine
    engine.dispose()


@pytest.fixture()
def audit_session(audit_engine):
    """Function-scoped session with ROLLBACK isolation."""
    connection = audit_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def patch_audit_dao(monkeypatch, audit_session):
    """Bind ``AuditLogDao`` to ``audit_session`` and make the service's
    response helpers / async lookups controllable."""

    @contextmanager
    def _fake_get_sync():
        yield audit_session

    @asynccontextmanager
    async def _fake_get_async():
        yield None

    monkeypatch.setattr("bisheng.database.models.audit_log.get_sync_db_session", _fake_get_sync)
    monkeypatch.setattr("bisheng.database.models.audit_log.bypass_tenant_filter", lambda: nullcontext())
    monkeypatch.setattr("bisheng.database.models.audit_log._db_dialect", lambda: "sqlite")
    monkeypatch.setattr("bisheng.api.services.audit_log.resp_200", lambda data=None: {"data": data})
    monkeypatch.setattr("bisheng.api.services.audit_log.bypass_tenant_filter", lambda: nullcontext())
    monkeypatch.setattr("bisheng.api.services.audit_log.get_async_db_session", _fake_get_async)


@pytest.fixture()
def audit_lookups(monkeypatch):
    """Replace the enrichment lookups with mocks; returns a namespace the
    test fills (``apps`` / ``tenants`` / ``users`` / ``group_users``)."""
    state = SimpleNamespace(apps=[], tenants=[], users=[], group_users=[], credentials=[])

    async def _apps_by_ids(session, app_ids):
        return [app for app in state.apps if app.id in set(app_ids)]

    async def _credentials(credential_ids):
        return [c for c in state.credentials if c.id in set(credential_ids)]

    async def _app_get(session, app_id):
        return next((app for app in state.apps if app.id == app_id), None)

    async def _tenants(tenant_ids):
        return [t for t in state.tenants if t.id in set(tenant_ids)]

    async def _users(user_ids):
        return [u for u in state.users if u.user_id in set(user_ids)]

    async def _group_users(group_ids, page=0, limit=0):
        return [g for g in state.group_users if g.group_id in set(group_ids)]

    monkeypatch.setattr("bisheng.api.services.audit_log.AppDao.alist_by_ids", AsyncMock(side_effect=_apps_by_ids))
    monkeypatch.setattr("bisheng.api.services.audit_log.AppDao.aget", AsyncMock(side_effect=_app_get))
    monkeypatch.setattr("bisheng.api.services.audit_log.TenantDao.aget_by_ids", AsyncMock(side_effect=_tenants))
    monkeypatch.setattr("bisheng.api.services.audit_log.UserDao.aget_user_by_ids", AsyncMock(side_effect=_users))
    monkeypatch.setattr(
        "bisheng.api.services.audit_log.UserGroupDao.aget_group_users", AsyncMock(side_effect=_group_users)
    )
    monkeypatch.setattr(
        "bisheng.api.services.audit_log.CredentialRepository.get_by_ids", AsyncMock(side_effect=_credentials)
    )
    return state


def make_app(app_id, *, name, slug, tenant_id, state="online", owner_user_id=7):
    return SimpleNamespace(
        id=app_id, name=name, slug=slug, tenant_id=tenant_id, state=state, owner_user_id=owner_user_id
    )


def make_credential(credential_id, *, key_prefix="bs-sak-", last4="ab12", subject_kind="service_account"):
    """A stand-in for ``ApiCredential`` — only the fields the mask needs; no
    plaintext exists on the real row either."""
    from bisheng.open_api.domain.models.api_credential import mask_key

    return SimpleNamespace(
        id=credential_id,
        key_prefix=key_prefix,
        last4=last4,
        subject_kind=subject_kind,
        key_mask=mask_key(last4, key_prefix),
    )


def make_user_payload(*, user_id, is_admin, is_global_super):
    u = MagicMock()
    u.user_id = user_id
    u.is_admin.return_value = is_admin
    u.is_global_super = is_global_super
    return u


def insert_audit(session, **kwargs):
    """Insert one ``auditlog`` row; unspecified columns stay NULL."""
    defaults = {"operator_id": 1, "operator_name": "alice", "tenant_id": 1, "operator_tenant_id": 1}
    defaults.update(kwargs)
    entry = AuditLog(**defaults)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry
