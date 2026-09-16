import importlib
from contextlib import asynccontextmanager

import pytest


class FakeRedis:
    def __init__(self):
        self.values: dict[str, object] = {}

    async def aget(self, key: str):
        return self.values.get(key)

    async def aset(self, key: str, value, expiration: int = 3600):
        self.values[key] = value
        return True

    async def asetNx(self, key: str, value, expiration: int = 3600):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def adelete(self, key: str):
        return int(self.values.pop(key, None) is not None)


@pytest.fixture
async def open_api_db(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.database.models.tenant import UserTenant
    from bisheng.open_api.domain.models import (
        ApiCredential,
        ApiCredentialDelegateScope,
        OpenApiTenantSetting,
        ServiceAccount,
    )
    from bisheng.user.domain.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(User.__table__.create)
        await connection.run_sync(UserTenant.__table__.create)
        await connection.run_sync(ServiceAccount.__table__.create)
        await connection.run_sync(ApiCredential.__table__.create)
        await connection.run_sync(ApiCredentialDelegateScope.__table__.create)
        await connection.run_sync(OpenApiTenantSetting.__table__.create)
    tenant_token = set_current_tenant_id(1)

    @asynccontextmanager
    async def session_factory():
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for module_name in (
        "bisheng.open_api.domain.repositories.credential_repository",
        "bisheng.open_api.domain.repositories.delegate_scope_repository",
        "bisheng.open_api.domain.repositories.owner_repository",
        "bisheng.open_api.domain.repositories.service_account_repository",
        "bisheng.open_api.domain.repositories.tenant_setting_repository",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_async_db_session", session_factory)
    yield session_factory
    current_tenant_id.reset(tenant_token)
    await engine.dispose()


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()

    async def get_fake_redis():
        return redis

    for module_name in (
        "bisheng.open_api.domain.services.credential_service",
        "bisheng.open_api.domain.services.credential_validator",
        "bisheng.open_api.domain.services.tenant_setting_service",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_redis_client", get_fake_redis)
    return redis


@asynccontextmanager
async def _mcp_app():
    """A FastAPI app carrying only the MCP route, with its session manager running.

    Not ``bisheng.main.app``: the route is registered at import time under
    ``open_platform.enabled``, which is off in the shipped test config. Each
    caller gets its own server because ``StreamableHTTPSessionManager.run()``
    may be entered once per instance.

    This is a plain context manager rather than an async fixture on purpose. The
    session manager's ``run()`` opens an anyio task group, and a task group has
    to be closed in the task that opened it — pytest-asyncio tears async
    fixtures down in a different task, which fails with "attempted to exit
    cancel scope in a different task". Entering it inside the test's own body
    keeps both ends in one task.
    """

    from fastapi import FastAPI

    from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
    from bisheng.open_api.mcp.server import build_mcp_route, mcp_session_manager_run, new_mcp_server

    server = new_mcp_server()
    app = FastAPI()
    register_open_api_exception_handlers(app)
    app.router.routes.append(build_mcp_route(server))
    async with mcp_session_manager_run(server):
        yield app


@pytest.fixture
def mcp_http():
    """``async with mcp_http(headers) as client`` → raw HTTP against the MCP route.

    For the transport-level facts a protocol client hides: the status code of a
    refusal, whether the bare path redirects, what a real ``Host`` header does.
    """

    import httpx

    @asynccontextmanager
    async def open_client(headers: dict[str, str] | None = None, **client_kwargs):
        async with _mcp_app() as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                headers=headers or {},
                **client_kwargs,
            ) as client:
                yield client

    return open_client


@pytest.fixture
def mcp_session():
    """``async with mcp_session(headers) as session`` → a real initialised ``ClientSession``.

    A genuine MCP client over the app in-process, because "any standard client
    connects with no changes" is only verified by a standard client: hand-rolled
    JSON-RPC posts would keep passing with a broken handshake.
    """

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    @asynccontextmanager
    async def connect(headers: dict[str, str] | None = None):
        async with _mcp_app() as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                headers=headers or {},
            ) as http_client:
                async with streamable_http_client("http://testserver/api/v2/mcp", http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _get_session_id,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        yield session

    return connect


@pytest.fixture
def audit_events(monkeypatch):
    events: list[dict] = []

    async def record(**kwargs):
        events.append(kwargs)
        return kwargs

    service_module = importlib.import_module("bisheng.open_api.domain.services.service_account_service")
    monkeypatch.setattr(service_module.AuditLogDao, "ainsert_v2", record)
    return events
