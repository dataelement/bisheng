"""Shared fixtures for the open_api (F049) test package.

Two execution modes share one fixture vocabulary:

* **In-process** (default, runs anywhere): an aiosqlite database holding the
  ``user`` / ``user_tenant`` / ``tenant`` / ``audit_log`` / ``api_credential`` /
  ``service_account`` tables at their current SQLModel shape, bound into the
  open_api modules through ``get_async_db_session`` monkeypatching (repo
  precedent: ``test/linsight/test_skill_dao.py``). Redis is a real server when
  ``OPEN_API_TEST_REDIS_URL`` (or the loaded ``settings.redis_url``) answers,
  otherwise ``fakeredis`` (test extra), otherwise the test skips.
* **CI integration** (design §7): the same fixtures against the test middleware
  by pointing ``OPEN_API_TEST_REDIS_URL`` at it; DB-backed API tests go through
  ``v2_client`` (``TestClient(app, raise_server_exceptions=False)``) and assert
  the *real* HTTP status on ``/api/v2/**``.

Import discipline (T008): this module never imports the T010 / T014 service
modules at top level - ``service_account_factory`` / ``credential_factory``
import them lazily inside the fixture body and ``pytest.skip`` while they do not
exist yet, so the package collects during the Test-First phase.

Proxy env: the repo-wide ``test/conftest.py`` has no proxy handling; a stray
``ALL_PROXY=socks://`` makes httpx-based clients fail on a missing ``socksio``
and turns the whole package into ERRORs, so ``_clear_proxy_env`` strips the
six variables for every test here.
"""

from __future__ import annotations

import importlib
import os
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

_PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")

# Fixed ids keep assertions readable and never collide with real seed data.
ROOT_TENANT_ID = 1
SUB_TENANT_ID = 2
TENANT_ADMIN_USER_ID = 90001
SUB_TENANT_ADMIN_USER_ID = 90002
HUMAN_USER_ID = 90010
# ``user.password`` is NOT NULL; seeded rows never authenticate (no login path
# is exercised here), so a one-character placeholder is enough.
SEED_PASSWORD_PLACEHOLDER = "x"

# Modules that bind ``get_async_db_session`` by name at import time. Missing
# ones (not implemented yet) are skipped silently.
_SESSION_PATCH_TARGETS = (
    "bisheng.core.database",
    "bisheng.core.database.manager",
    "bisheng.database.models.tenant",
    "bisheng.database.models.audit_log",
    "bisheng.user.domain.models.user",
    "bisheng.open_api.domain.models.api_credential",
    "bisheng.open_api.domain.models.service_account",
    "bisheng.open_api.domain.services.credential_service",
    "bisheng.open_api.domain.services.credential_validator",
    "bisheng.open_api.domain.services.service_account_service",
    "bisheng.open_api.api.dependencies",
)
_REDIS_PATCH_TARGETS = (
    "bisheng.open_api.domain.services.credential_service",
    "bisheng.open_api.domain.services.credential_validator",
    "bisheng.open_api.domain.services.service_account_service",
    "bisheng.open_api.api.dependencies",
)
_TABLES = ("tenant", "user", "user_tenant", "auditlog", "api_credential", "service_account")


def _optional_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    """Strip proxy variables - see module docstring (memory: missing socksio → whole batch ERROR)."""
    for key in _PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Database (aiosqlite) + session binding
# ---------------------------------------------------------------------------


@pytest.fixture()
async def oapi_engine():
    """Fresh in-memory aiosqlite engine with the six F049-relevant tables."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel

    # Populate SQLModel.metadata with the real model definitions.
    importlib.import_module("bisheng.database.models.tenant")
    importlib.import_module("bisheng.database.models.audit_log")
    importlib.import_module("bisheng.user.domain.models.user")
    importlib.import_module("bisheng.open_api.domain.models")

    tables = [SQLModel.metadata.tables[name] for name in _TABLES if name in SQLModel.metadata.tables]
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture()
async def oapi_db(oapi_engine, monkeypatch):
    """Bind ``get_async_db_session`` in every open_api-facing module to ``oapi_engine``.

    Returns the session factory (an ``asynccontextmanager``) so tests can seed
    or inspect rows directly: ``async with oapi_db() as session: ...``.
    """
    from sqlmodel.ext.asyncio.session import AsyncSession

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=oapi_engine, expire_on_commit=False)
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


@pytest.fixture()
def tenant_admin_payload():
    """A tenant administrator who is **not** global super (admin short-circuits ReBAC).

    Only the identity is built here; the ``get_service_account_admin``
    dependency is overridden by API tests that need it admitted.
    """
    return _payload(TENANT_ADMIN_USER_ID, "oapi-tenant-admin", ROOT_TENANT_ID)


@pytest.fixture()
async def human_user(oapi_db):
    """Enabled natural person of the root tenant - the default resource owner (AC-23)."""
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import USER_TYPE_HUMAN, User

    async with oapi_db() as session:
        user = User(
            user_id=HUMAN_USER_ID,
            user_name="oapi-human-owner",
            password=SEED_PASSWORD_PLACEHOLDER,
            user_type=USER_TYPE_HUMAN,
            delete=0,
        )
        session.add(user)
        await session.flush()
        session.add(UserTenant(user_id=user.user_id, tenant_id=ROOT_TENANT_ID, status="active", is_active=1))
        await session.commit()
        return user


@pytest.fixture()
async def sub_tenant(oapi_db):
    """A child tenant (id 2, parent Root) plus its non-super admin payload for cross-tenant assertions."""
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import USER_TYPE_HUMAN, User

    async with oapi_db() as session:
        session.add(
            Tenant(
                id=SUB_TENANT_ID,
                tenant_code="oapi-sub",
                tenant_name="OpenAPI sub tenant",
                status="active",
                parent_tenant_id=ROOT_TENANT_ID,
            )
        )
        admin = User(
            user_id=SUB_TENANT_ADMIN_USER_ID,
            user_name="oapi-sub-admin",
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
        admin_payload=_payload(SUB_TENANT_ADMIN_USER_ID, "oapi-sub-admin", SUB_TENANT_ID),
    )


# ---------------------------------------------------------------------------
# Factories (lazy import of T014 / T010 - the package must collect before they exist)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def service_account_factory(oapi_db, human_user, tenant_admin_payload):
    """``await service_account_factory(name=..., resource_owner_user_id=..., ...)`` → ServiceAccount row.

    Goes through ``ServiceAccountService.create(operator, data)`` (T014) so the
    D1 single-transaction create path is exercised; skips while T014 is absent.
    """
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.open_api.domain.schemas.service_account import ServiceAccountCreate

    async def _create(
        name: str = "oapi-sa",
        *,
        resource_owner_user_id: int | None = None,
        description: str | None = "created by test",
        operator=None,
    ):
        service_module = _optional_module("bisheng.open_api.domain.services.service_account_service")
        if service_module is None:
            pytest.skip("ServiceAccountService (T014) not implemented yet")
        operator = operator or tenant_admin_payload
        set_current_tenant_id(operator.tenant_id)
        data = ServiceAccountCreate(
            name=name,
            description=description,
            resource_owner_user_id=resource_owner_user_id or human_user.user_id,
        )
        return await service_module.ServiceAccountService.create(operator, data)

    return _create


@pytest.fixture()
async def credential_factory(oapi_db, tenant_admin_payload):
    """``await credential_factory(subject_id, scopes=[...], ...)`` → whatever ``CredentialService.issue`` returns (plaintext + row).

    Uses ``CredentialService.issue(operator, subject_kind, subject_id, KeyIssueRequest)``
    (T010); skips while T010 is absent.
    """
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_SERVICE_ACCOUNT
    from bisheng.open_api.domain.schemas.credential import KeyIssueRequest

    async def _issue(
        subject_id: int | str,
        *,
        scopes: list[str] | None = None,
        name: str = "oapi-key",
        expires_at: datetime | None = None,
        subject_kind: str = SUBJECT_KIND_SERVICE_ACCOUNT,
        operator=None,
    ):
        service_module = _optional_module("bisheng.open_api.domain.services.credential_service")
        if service_module is None:
            pytest.skip("CredentialService (T010) not implemented yet")
        request = KeyIssueRequest(name=name, scopes=scopes or [], expires_at=expires_at)
        return await service_module.CredentialService.issue(
            operator or tenant_admin_payload, subject_kind, str(subject_id), request
        )

    return _issue


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def _resolve_redis_url() -> str | None:
    url = os.environ.get("OPEN_API_TEST_REDIS_URL")
    if url:
        return url
    try:
        from bisheng.common.services.config_service import settings

        candidate = getattr(settings, "redis_url", None)
        return candidate if isinstance(candidate, str) else None
    except Exception:  # settings may be a MagicMock under the repo-wide premock
        return None


def _real_redis_client_class():
    """``RedisClient``, loaded from source when the repo-wide premock replaced its module.

    ``test/fixtures/mock_services.premock_import_chain`` installs a ``MagicMock``
    for ``bisheng.core.cache.redis_conn`` (it is on the import chain of
    ``tenant_service``), so a plain import here yields a mock whose
    ``__new__`` raises ``TypeError: issubclass() arg 1 must be a class``. The
    module itself imports cleanly (``redis`` / ``redis.exceptions`` are the real
    packages), so load it from its file under a private name — leaving
    ``sys.modules["bisheng.core.cache.redis_conn"]`` untouched for every other
    test package that relies on the mock.
    """
    import sys

    module = sys.modules.get("bisheng.core.cache.redis_conn")
    candidate = getattr(module, "RedisClient", None)
    if isinstance(candidate, type):
        return candidate

    import importlib.util
    import pathlib

    import bisheng

    private_name = "_open_api_test_redis_conn"
    if private_name in sys.modules:
        return sys.modules[private_name].RedisClient
    path = pathlib.Path(bisheng.__file__).parent / "core" / "cache" / "redis_conn.py"
    spec = importlib.util.spec_from_file_location(private_name, path)
    real = importlib.util.module_from_spec(spec)
    sys.modules[private_name] = real
    spec.loader.exec_module(real)
    return real.RedisClient


@pytest.fixture()
async def redis_client(monkeypatch):
    """A ``RedisClient`` on a real Redis when reachable, else fakeredis; ``oapi:*`` keys cleaned afterwards.

    Also patched into every open_api service module that binds
    ``get_redis_client`` by name, so the code under test and the assertions
    talk to the same store. Skips when neither backend is available.
    """
    RedisClient = _real_redis_client_class()

    client = None
    url = _resolve_redis_url()
    if url:
        try:
            import redis as _redis

            _redis.Redis.from_url(url, socket_connect_timeout=1).ping()
            client = RedisClient(url)
        except Exception:
            client = None
    if client is None:
        fakeredis = _optional_module("fakeredis")
        fakeredis_aio = _optional_module("fakeredis.aioredis")
        if fakeredis is None or fakeredis_aio is None:
            pytest.skip("no reachable Redis (OPEN_API_TEST_REDIS_URL / settings.redis_url) and fakeredis not installed")
        server = fakeredis.FakeServer()
        client = RedisClient.__new__(RedisClient)
        client.connection = fakeredis.FakeStrictRedis(server=server)
        client.async_connection = fakeredis_aio.FakeRedis(server=server)

    async def _get_redis_client():
        return client

    for target in _REDIS_PATCH_TARGETS:
        module = _optional_module(target)
        if module is not None and hasattr(module, "get_redis_client"):
            monkeypatch.setattr(module, "get_redis_client", _get_redis_client)

    yield client

    try:
        keys = await client.akeys("oapi:*")
        for key in keys:
            await client.adelete(key)
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# HTTP client for /api/v2 (real HTTP status assertions)
# ---------------------------------------------------------------------------


@pytest.fixture()
def v2_client(monkeypatch):
    """``TestClient(app, raise_server_exceptions=False)`` with a no-op lifespan.

    ``raise_server_exceptions=False`` lets the dedicated ``/api/v2`` exception
    handler produce its real 401 / 403 / 503 instead of the test client
    re-raising. Skips (never falls back to a stub app - a stub would make v2
    assertions meaningless) when the application cannot be built.
    """
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _noop_lifespan(app):
        yield

    try:
        monkeypatch.setattr("bisheng.main.lifespan", _noop_lifespan)
        from bisheng.main import create_app

        app = create_app()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"cannot build FastAPI app for v2 tests: {exc!r}")

    from starlette.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ---------------------------------------------------------------------------
# F048 outage simulation
# ---------------------------------------------------------------------------


@pytest.fixture()
def fga_down(monkeypatch):
    """Make every F048 decision raise ``PermissionServiceUnavailableError`` (→ 503 on /api/v2, AC-34).

    Patches the single choke point ``_ensure_f048_runtime`` that all
    ``get_f048_*`` accessors await, so it holds regardless of which module
    imported ``check_business_action`` / ``require_business_action`` by name.
    """
    from bisheng.common.errcode.permission import PermissionServiceUnavailableError
    from bisheng.permission.application import access

    async def _unavailable(*args: Any, **kwargs: Any):
        raise PermissionServiceUnavailableError()

    monkeypatch.setattr(access, "_ensure_f048_runtime", _unavailable)
    return PermissionServiceUnavailableError
