"""Shared fixtures for the app_runtime (F054) test package.

Runs anywhere by default: an in-memory aiosqlite database holding the tables
F054 touches (``tenant`` / ``user`` / ``user_tenant`` / ``department`` /
``user_department`` / ``auditlog`` / ``app`` / ``app_version`` /
``app_instance``) at their current SQLModel shape, bound into the app_runtime
modules by monkeypatching ``get_async_db_session`` (repo precedent:
``test/open_api/conftest.py``, ``test/linsight/test_skill_dao.py``). Tests that
genuinely need OpenFGA or MySQL say so themselves and skip when the middleware
is absent — nothing here weakens an assertion to make it pass locally.

Four things this file exists to prevent:

* **Admin short-circuit false greens.** ``tenant_admin_payload`` is a *tenant*
  administrator with ``is_global_super=False``. A global super admin is
  short-circuited to ALLOW before ReBAC is consulted, so verifying "visible
  scope works" with one proves nothing (design pit 26 / repo memory).
* **Latin-1 header blindness.** ``chinese_name_user`` has a Chinese display
  name. HTTP headers are latin-1; the injected ``X-BiSheng-User-Name`` /
  ``Dept-Name`` / ``Dept-Path`` must be percent-encoded, and with the usual
  English test account that bug is invisible (design pit 9).
* **A half-stubbed orchestrator.** ``fake_orchestrator`` replaces **all ten**
  ``orchestrator_client`` methods. Miss one and it silently falls through to
  real HTTP against 127.0.0.1:8091 — which only surfaces as a connection error
  in CI, far from the test that caused it. The fixture asserts the stub set
  matches the facade's public method set, so a new method breaks loudly here.
* **Proxy-induced mass ERRORs.** A stray ``ALL_PROXY=socks://`` makes every
  httpx client fail on the missing ``socksio`` extra and turns the whole
  package into ERRORs. The autouse fixture strips the six variables.

Import discipline: nothing from ``bisheng.app_runtime.domain.services`` is
imported at module level. Fixtures import lazily inside their body and
``pytest.skip`` while the service does not exist yet, so this package still
collects during the Test-First phase.
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

_PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")

# Fixed ids keep assertions readable and never collide with real seed data.
ROOT_TENANT_ID = 1
SUB_TENANT_ID = 2
TENANT_ADMIN_USER_ID = 91001
SUB_TENANT_ADMIN_USER_ID = 91002
NORMAL_USER_ID = 91010
CHINESE_NAME_USER_ID = 91011
OWNER_USER_ID = 91020

CHINESE_USER_NAME = "张三丰"
CHINESE_DEPT_NAME = "研发中心"
CHINESE_DEPT_BUSINESS_KEY = "BS@f054dept"

# ``user.password`` is NOT NULL; seeded rows never authenticate.
SEED_PASSWORD_PLACEHOLDER = "x"

# Modules that bind ``get_async_db_session`` by name at import time. Absent
# ones (not implemented yet) are skipped silently — the tuple is the union of
# what exists today and what waves 2-3 will add.
_SESSION_PATCH_TARGETS = (
    "bisheng.core.database",
    "bisheng.core.database.manager",
    "bisheng.database.models.app",
    "bisheng.database.models.app_version",
    "bisheng.database.models.app_instance",
    "bisheng.database.models.audit_log",
    "bisheng.database.models.department",
    "bisheng.database.models.tenant",
    "bisheng.user.domain.models.user",
    "bisheng.app_runtime.domain.services.app_provision_service",
    "bisheng.app_runtime.domain.services.app_state_service",
    "bisheng.app_runtime.domain.services.app_meta_service",
    "bisheng.app_runtime.domain.services.app_query_service",
    "bisheng.app_runtime.domain.services.entry_authz_service",
    "bisheng.app_runtime.domain.services.f048_app_permission",
    "bisheng.app_runtime.api.endpoints.internal_app_proxy",
    "bisheng.app_runtime.api.endpoints.apps",
)

_TABLES = (
    "tenant",
    "user",
    "user_tenant",
    "department",
    "user_department",
    "auditlog",
    "app",
    "app_version",
    "app_instance",
    # F055's table. Present but empty on purpose: that is the MVP reality (the
    # seed runs on first boot) and it exercises F054's DEFAULT_TIERS fallback
    # through its intended branch instead of through a missing-table error.
    "resource_tier",
)

#: Every method ``orchestrator_client`` exposes (design §4.2 ①). The
#: ``fake_orchestrator`` fixture stubs exactly this set — see the module
#: docstring for why "exactly" matters.
ORCHESTRATOR_METHODS = (
    "build",
    "build_status",
    "deploy",
    "stop",
    "destroy",
    "probe",
    "admission",
    "status",
    "logs",
    "runtime_status",
)


def _optional_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    """Strip proxy variables — see the module docstring."""
    for key in _PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _no_super_admin_probe(monkeypatch):
    """``_check_is_global_super`` answers False without touching the real stack.

    Left alone it resolves through Redis and the *real* database manager, whose
    initialisation registers the tenant-filter ORM listeners **process-wide**.
    Those listeners then rewrite SELECTs in every test package that runs after
    this one — which showed up as an unrelated F055 pipeline test failing only
    when F054 ran first. A test that needs a super admin sets
    ``is_global_super=True`` on its payload instead; nothing here is verified
    through this probe.
    """
    from bisheng.utils.http_middleware import _check_is_global_super  # noqa: F401 - import-time guard

    async def _never_super(*args: Any, **kwargs: Any) -> bool:
        return False

    for target in ("bisheng.utils.http_middleware", "bisheng.app_runtime.domain.services.entry_authz_service"):
        module = _optional_module(target)
        if module is not None and hasattr(module, "_check_is_global_super"):
            monkeypatch.setattr(module, "_check_is_global_super", _never_super)


# ---------------------------------------------------------------------------
# Database (aiosqlite) + session binding
# ---------------------------------------------------------------------------


@pytest.fixture()
async def app_engine():
    """Fresh in-memory aiosqlite engine carrying the F054-relevant tables."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel

    for module in (
        "bisheng.database.models.tenant",
        "bisheng.database.models.audit_log",
        "bisheng.database.models.department",
        "bisheng.user.domain.models.user",
        "bisheng.database.models.app",
        "bisheng.database.models.app_version",
        "bisheng.database.models.app_instance",
        "bisheng.database.models.resource_tier",
    ):
        importlib.import_module(module)

    tables = [SQLModel.metadata.tables[name] for name in _TABLES if name in SQLModel.metadata.tables]
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture()
async def app_db(app_engine, monkeypatch):
    """Bind ``get_async_db_session`` in every app_runtime-facing module to ``app_engine``.

    Returns the session factory (an ``asynccontextmanager``) so a test can seed
    or inspect rows directly: ``async with app_db() as session: ...``.
    """
    from sqlmodel.ext.asyncio.session import AsyncSession

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=app_engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for target in _SESSION_PATCH_TARGETS:
        module = _optional_module(target)
        if module is not None and hasattr(module, "get_async_db_session"):
            monkeypatch.setattr(module, "get_async_db_session", _session)
    return _session


# ---------------------------------------------------------------------------
# Principals
# ---------------------------------------------------------------------------


def _payload(user_id: int, user_name: str, tenant_id: int):
    from bisheng.common.dependencies.user_deps import UserPayload

    # ``user_role=[]`` skips the UserRoleDao lookup in LoginUser.__init__;
    # ``is_global_super=False`` keeps the admin short-circuit out of the way.
    return UserPayload(user_id=user_id, user_name=user_name, user_role=[], tenant_id=tenant_id, is_global_super=False)


async def _seed_user(app_db, user_id: int, user_name: str, tenant_id: int = ROOT_TENANT_ID):
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import USER_TYPE_HUMAN, User

    async with app_db() as session:
        user = User(
            user_id=user_id,
            user_name=user_name,
            password=SEED_PASSWORD_PLACEHOLDER,
            user_type=USER_TYPE_HUMAN,
            delete=0,
        )
        session.add(user)
        await session.flush()
        session.add(UserTenant(user_id=user.user_id, tenant_id=tenant_id, status="active", is_active=1))
        await session.commit()
        return user


@pytest.fixture()
def tenant_admin_payload():
    """A tenant administrator who is **not** global super — see the module docstring."""
    return _payload(TENANT_ADMIN_USER_ID, "f054-tenant-admin", ROOT_TENANT_ID)


@pytest.fixture()
async def normal_user(app_db):
    """An ordinary natural person of the root tenant — the default grantee."""
    user = await _seed_user(app_db, NORMAL_USER_ID, "f054-normal-user")
    return SimpleNamespace(
        user_id=user.user_id,
        user_name=user.user_name,
        payload=_payload(user.user_id, user.user_name, ROOT_TENANT_ID),
    )


@pytest.fixture()
async def app_owner(app_db):
    """The natural person owning apps built by ``app_factory``."""
    user = await _seed_user(app_db, OWNER_USER_ID, "f054-app-owner")
    return SimpleNamespace(
        user_id=user.user_id,
        user_name=user.user_name,
        payload=_payload(user.user_id, user.user_name, ROOT_TENANT_ID),
    )


@pytest.fixture()
async def chinese_name_user(app_db):
    """A user whose display name and primary department are Chinese (design pit 9).

    Returns the user plus its department so header round-trip tests can assert
    on all three non-ASCII header values (``User-Name`` / ``Dept-Name`` /
    ``Dept-Path``) without re-seeding.
    """
    from bisheng.database.models.department import Department, UserDepartment

    user = await _seed_user(app_db, CHINESE_NAME_USER_ID, CHINESE_USER_NAME)
    async with app_db() as session:
        department = Department(
            dept_id=CHINESE_DEPT_BUSINESS_KEY,
            name=CHINESE_DEPT_NAME,
            parent_id=None,
            tenant_id=ROOT_TENANT_ID,
        )
        session.add(department)
        await session.flush()
        # Explicit id: ``user_department.id`` is BIGINT, and SQLite only
        # autoincrements a column declared exactly ``INTEGER PRIMARY KEY``.
        session.add(UserDepartment(id=1, user_id=user.user_id, department_id=department.id, is_primary=1))
        await session.commit()
        department_id = department.id
    return SimpleNamespace(
        user_id=user.user_id,
        user_name=CHINESE_USER_NAME,
        payload=_payload(user.user_id, CHINESE_USER_NAME, ROOT_TENANT_ID),
        department_id=department_id,
        # ``Department.dept_id`` — the business key that goes into the header,
        # NOT the autoincrement id (design §4.2 ③).
        department_business_key=CHINESE_DEPT_BUSINESS_KEY,
        department_name=CHINESE_DEPT_NAME,
    )


@pytest.fixture()
async def sub_tenant(app_db):
    """A child tenant (id 2, parent Root) plus its non-super admin payload."""
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import USER_TYPE_HUMAN, User

    async with app_db() as session:
        session.add(
            Tenant(
                id=SUB_TENANT_ID,
                tenant_code="f054-sub",
                tenant_name="F054 sub tenant",
                status="active",
                parent_tenant_id=ROOT_TENANT_ID,
            )
        )
        admin = User(
            user_id=SUB_TENANT_ADMIN_USER_ID,
            user_name="f054-sub-admin",
            password=SEED_PASSWORD_PLACEHOLDER,
            user_type=USER_TYPE_HUMAN,
            delete=0,
        )
        session.add(admin)
        await session.flush()
        session.add(UserTenant(user_id=admin.user_id, tenant_id=SUB_TENANT_ID, status="active", is_active=1))
        await session.commit()
    return SimpleNamespace(
        tenant_id=SUB_TENANT_ID,
        admin_user_id=SUB_TENANT_ADMIN_USER_ID,
        admin_payload=_payload(SUB_TENANT_ADMIN_USER_ID, "f054-sub-admin", SUB_TENANT_ID),
    )


# ---------------------------------------------------------------------------
# Domain factories
# ---------------------------------------------------------------------------


@pytest.fixture()
async def app_factory(app_db, app_owner):
    """``await app_factory(state=..., owner_user_id=..., tenant_id=...)`` → (App, AppVersion).

    Goes straight through the DAOs rather than a service: the permission and
    read-side tests need a row in a given state without asserting anything
    about how it got there, and ``AppStateService`` (wave 3) cannot manufacture
    an ``online`` app without a live orchestrator.
    """
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.database.models.app import App, AppDao
    from bisheng.database.models.app_version import VERSION_KIND_INITIAL, AppVersion, AppVersionDao

    counter = {"n": 0}

    async def _create(
        *,
        state: str = "online",
        owner_user_id: int | None = None,
        tenant_id: int = ROOT_TENANT_ID,
        slug: str | None = None,
        name: str | None = None,
        runtime: str = "python3.11",
        tier_id: str = "standard",
        with_version: bool = True,
    ):
        counter["n"] += 1
        suffix = counter["n"]
        set_current_tenant_id(tenant_id)
        async with app_db() as session:
            app_row = App(
                slug=slug or f"f054-app-{suffix}",
                name=name or f"F054 app {suffix}",
                description="seeded by app_factory",
                owner_user_id=owner_user_id if owner_user_id is not None else app_owner.user_id,
                tenant_id=tenant_id,
                state=state,
            )
            await AppDao.acreate(session, app_row)
            version_row = None
            if with_version:
                version_row = AppVersion(
                    app_id=app_row.id,
                    version_no=1,
                    kind=VERSION_KIND_INITIAL,
                    code_object_key=f"apps/{app_row.id}/versions/v1/code.tar.gz",
                    manifest={"port": 8080, "runtime": runtime},
                    capabilities={},
                    injections={},
                    tier_id=tier_id,
                    runtime=runtime,
                    submitted_at=datetime.now(),
                )
                await AppVersionDao.ainsert(session, version_row)
                app_row.current_version_id = version_row.id
                session.add(app_row)
            await session.commit()
        return app_row, version_row

    return _create


# ---------------------------------------------------------------------------
# Orchestrator stub
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_orchestrator(monkeypatch):
    """Replace **all ten** ``orchestrator_client`` methods with programmable stubs.

    Returns a namespace with ``calls`` (an ordered list of ``(method, kwargs)``)
    and ``responses`` (a per-method dict the test may overwrite before acting).
    Default responses follow the shapes in design §4.2 ①.

    Skips while ``orchestrator_client`` (T047) does not exist. Once it does, the
    fixture asserts its own stub set equals the facade's public method set — a
    newly added facade method fails here rather than silently escaping to real
    HTTP against 127.0.0.1:8091.
    """
    module = _optional_module("bisheng.app_runtime.domain.services.orchestrator_client")
    if module is None:
        pytest.skip("orchestrator_client (T047) not implemented yet")

    client = getattr(module, "orchestrator_client", None) or module
    public = {
        name
        for name in dir(client)
        if not name.startswith("_")
        and callable(getattr(client, name, None))
        and not isinstance(getattr(client, name), type)
    }
    unstubbed = public - set(ORCHESTRATOR_METHODS)
    assert not unstubbed, (
        f"orchestrator_client gained method(s) {sorted(unstubbed)} that fake_orchestrator does not stub; "
        "an unstubbed method falls through to real HTTP against runtime-manager"
    )

    responses: dict[str, Any] = {
        "build": {"build_id": "bld-1", "status": "building"},
        "build_status": {
            "status": "succeeded",
            "stage": "docker_build",
            "message": "",
            "tail": "",
            "image_ref": "bisheng-app/f054-app-1:1-abcdef12",
        },
        "deploy": {"instance_id": "inst-1", "phase": "starting"},
        "stop": {"phase": "stopped"},
        "destroy": {},
        "probe": {"ready": True, "reason": ""},
        "admission": {
            "admitted": True,
            "reason": "",
            "snapshot": {"mem_available_mb": 8192, "committed_mb": 1024, "total_mb": 32768, "cpu": 8},
        },
        "status": {
            "instance_id": "inst-1",
            "phase": "running",
            "health": "healthy",
            "current_version_id": None,
            "started_at": None,
            "restart_count": 0,
            "last_probe_at": None,
        },
        "logs": {"lines": []},
        "runtime_status": {
            "backend_available": True,
            "supported_runtimes": ["python3.11"],
            "capacity": {"mem_available_mb": 8192, "committed_mb": 1024, "total_mb": 32768, "cpu": 8},
            "preflight": [],
        },
    }
    calls: list[tuple[str, dict[str, Any]]] = []

    def _make(name: str):
        async def _stub(*args: Any, **kwargs: Any):
            calls.append((name, kwargs))
            value = responses[name]
            if isinstance(value, Exception):
                raise value
            return value

        return _stub

    for name in ORCHESTRATOR_METHODS:
        monkeypatch.setattr(client, name, _make(name), raising=False)

    return SimpleNamespace(calls=calls, responses=responses)


# ---------------------------------------------------------------------------
# F048 outage simulation + audit capture
# ---------------------------------------------------------------------------


@pytest.fixture()
def fga_down(monkeypatch):
    """Make every F048 decision raise ``PermissionServiceUnavailableError`` (AC-12).

    Patches the single choke point ``_ensure_f048_runtime`` that all
    ``get_f048_*`` accessors await, so it holds no matter which module imported
    ``check_business_action`` by name. Every F054 path must translate this into
    a **deny** (16146) — never into a pass-through.
    """
    from bisheng.common.errcode.permission import PermissionServiceUnavailableError
    from bisheng.permission.application import access

    async def _unavailable(*args: Any, **kwargs: Any):
        raise PermissionServiceUnavailableError()

    monkeypatch.setattr(access, "_ensure_f048_runtime", _unavailable)
    return PermissionServiceUnavailableError


@pytest.fixture()
def audit_sink(monkeypatch):
    """Capture ``AuditLogDao.ainsert_v2`` calls instead of writing rows.

    Returns the list of keyword dicts, in call order — assert on
    ``[call["action"] for call in audit_sink]`` for AC-65.
    """
    from bisheng.database.models.audit_log import AuditLogDao

    captured: list[dict[str, Any]] = []

    async def _capture(*args: Any, **kwargs: Any):
        captured.append(dict(kwargs))
        return None

    monkeypatch.setattr(AuditLogDao, "ainsert_v2", classmethod(lambda cls, *a, **kw: _capture(*a, **kw)))
    return captured


# ---------------------------------------------------------------------------
# F048 projection + tenant-admin stand-ins (wave 3)
# ---------------------------------------------------------------------------

#: Modules that reach the F048 composition root by name. Patching every one of
#: them is what keeps a service honest: a module that grew its own import path
#: and is missing here fails loudly against a real (absent) registry instead of
#: quietly using the stub.
_PERMISSION_ADAPTER_TARGETS = (
    "bisheng.app_runtime.domain.services.app_provision_service",
    "bisheng.app_runtime.domain.services.app_state_service",
    "bisheng.app_runtime.domain.services.entry_authz_service",
)

_TENANT_ADMIN_TARGETS = (
    "bisheng.app_runtime.domain.services.app_state_service",
    "bisheng.app_runtime.domain.services.app_meta_service",
    "bisheng.app_runtime.domain.services.app_query_service",
)


@pytest.fixture()
def fake_permission_projection(monkeypatch):
    """Stand in for ``get_f048_resource_adapter("app")``.

    OpenFGA is not reachable in a unit run, and the adapter itself is covered by
    ``test_app_permission_registration.py``. What the wave-3 services owe is
    that they *call* it — creation projects the owner (AC-11), deletion projects
    the removal — so the stub records calls and the tests assert on them.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Adapter:
        async def load_permission_record(self, resource_id: str):
            calls.append(("load_permission_record", {"resource_id": resource_id}))
            return SimpleNamespace(resource_id=resource_id)

        async def authorize_created(self, **kwargs):
            calls.append(("authorize_created", kwargs))

        async def project_delete(self, **kwargs):
            calls.append(("project_delete", kwargs))

    adapter = _Adapter()

    async def _get_adapter(resource_type: str):
        assert resource_type == "app"
        return adapter

    for target in _PERMISSION_ADAPTER_TARGETS:
        module = _optional_module(target)
        if module is not None and hasattr(module, "get_f048_resource_adapter"):
            monkeypatch.setattr(module, "get_f048_resource_adapter", _get_adapter)
    return SimpleNamespace(calls=calls, adapter=adapter, actions=lambda: [name for name, _ in calls])


@pytest.fixture()
def tenant_admins(monkeypatch):
    """``tenant_admins.grant(user_id, tenant_id)`` → that pair passes ``check_tenant_admin``.

    Real tenant-admin resolution goes through the permission application layer;
    here the point is only *which* branch of the business pre-check a caller
    lands in, so the membership set is explicit and readable in the test.
    """
    granted: set[tuple[int, int]] = set()

    async def _check(user_id: int, tenant_id: int) -> bool:
        return (int(user_id), int(tenant_id)) in granted

    for target in _TENANT_ADMIN_TARGETS:
        module = _optional_module(target)
        if module is not None and hasattr(module, "check_tenant_admin"):
            monkeypatch.setattr(module, "check_tenant_admin", _check)
    return SimpleNamespace(grant=lambda user_id, tenant_id: granted.add((int(user_id), int(tenant_id))))


@pytest.fixture()
def api_app():
    """``api_app(payload)`` → an ``httpx.AsyncClient`` bound to the F054 router.

    Two deliberate choices:

    * **ASGITransport, not ``TestClient``.** ``TestClient`` drives the app on its
      own event loop, while the in-memory aiosqlite engine and every ContextVar
      these tests set live on the test's loop — the first DB call would fail with
      "attached to a different loop". Driving the ASGI app in-process keeps one
      loop end to end.
    * **The router alone, not ``bisheng.main.create_app``.** The full app brings
      its middleware chain, which re-resolves tenants against a database these
      tests replaced. A failure here should point at F054, not at an unrelated
      module's import.
    """
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from bisheng.app_runtime.api.exception_handlers import register_app_runtime_exception_handlers
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode

    def _handle(_request, exc: BaseErrorCode) -> JSONResponse:
        # Mirrors bisheng.main.handle_http_exception: business errors ride in a
        # 200 envelope, because the platform SPA turns a real 403/404 on a GET
        # into a full-page redirect (design pit 25).
        return JSONResponse(status_code=200, content=exc.to_dict())

    def _build(payload=None):
        from bisheng.app_runtime.api.router import router as app_runtime_router

        app = FastAPI(exception_handlers={BaseErrorCode: _handle})
        register_app_runtime_exception_handlers(app)
        app.include_router(app_runtime_router, prefix="/api/v1")
        if payload is not None:
            app.dependency_overrides[UserPayload.get_login_user] = lambda: payload
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    return _build
