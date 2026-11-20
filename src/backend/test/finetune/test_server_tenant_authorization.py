"""Finetune server management must never write another tenant's namespace."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import sqlite

from bisheng.finetune.api import server as api
from bisheng.finetune.domain.models import server as models


async def call_add(server, user):
    return await api.add_server(server=server, login_user=user)


async def call_delete(server_id, user):
    return await api.delete_server(server_id=server_id, login_user=user)


@pytest.fixture
def server_case(monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.permission import application
    from bisheng.utils import http_middleware

    token = set_current_tenant_id(3)
    monkeypatch.setattr(application, "is_tenant_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(http_middleware, "_check_is_global_super", AsyncMock(return_value=False))
    user = SimpleNamespace(user_id=33, tenant_id=3)
    insert = AsyncMock(side_effect=lambda row, **kwargs: row)
    delete = AsyncMock()
    monkeypatch.setattr(models.ServerDao, "insert", insert)
    monkeypatch.setattr(models.ServerDao, "delete", delete)
    monkeypatch.setattr(
        models.ServerDao,
        "find_server",
        AsyncMock(return_value=models.Server(id=70, tenant_id=1, endpoint="", server="synthetic")),
    )
    yield SimpleNamespace(user=user, insert=insert, delete=delete)
    current_tenant_id.reset(token)


async def test_create_ignores_client_tenant_and_derives_current_scope(server_case):
    request = models.ServerCreate(endpoint="", server="synthetic", tenant_id=4)
    await call_add(request, server_case.user)
    assert server_case.insert.call_args.args[0].tenant_id == 3


@pytest.mark.parametrize("owner", [1, 4])
async def test_delete_foreign_or_root_server_rejected(server_case, monkeypatch, owner):
    monkeypatch.setattr(
        models.ServerDao,
        "find_server",
        AsyncMock(return_value=models.Server(id=70, tenant_id=owner, endpoint="", server="synthetic")),
    )
    with pytest.raises(HTTPException):
        await call_delete(70, server_case.user)
    server_case.delete.assert_not_awaited()


async def test_delete_sql_includes_verified_tenant(monkeypatch):
    session = MagicMock()
    session.exec = AsyncMock(return_value=SimpleNamespace(rowcount=1))
    session.commit = AsyncMock()

    @asynccontextmanager
    async def cm():
        yield session

    monkeypatch.setattr(models, "get_async_db_session", cm)
    await models.ServerDao.delete(70, tenant_id=3)
    statement = session.exec.call_args.args[0]
    sql = str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    assert "server.id = 70" in sql
    assert "server.tenant_id = 3" in sql


async def test_own_server_delete_uses_verified_scope(server_case, monkeypatch):
    monkeypatch.setattr(
        models.ServerDao,
        "find_server",
        AsyncMock(return_value=models.Server(id=70, tenant_id=3, endpoint="", server="synthetic")),
    )
    server_case.delete.return_value = True
    await call_delete(70, server_case.user)
    server_case.delete.assert_awaited_once_with(70, tenant_id=3)


@pytest.mark.parametrize("operation", ["add", "delete"])
@pytest.mark.parametrize(
    "scope,is_super,is_admin,allowed",
    [
        (1, False, True, False),
        (1, True, False, True),
        (3, False, False, False),
        (None, True, True, False),
        (3, True, False, True),
    ],
)
async def test_server_management_scope_policy(server_case, monkeypatch, operation, scope, is_super, is_admin, allowed):
    from bisheng.core.context.tenant import current_tenant_id
    from bisheng.permission import application
    from bisheng.utils import http_middleware

    current_tenant_id.set(scope)
    monkeypatch.setattr(application, "is_tenant_admin", AsyncMock(return_value=is_admin))
    monkeypatch.setattr(http_middleware, "_check_is_global_super", AsyncMock(return_value=is_super))
    monkeypatch.setattr(
        models.ServerDao,
        "find_server",
        AsyncMock(return_value=models.Server(id=70, tenant_id=scope, endpoint="", server="synthetic")),
    )
    server_case.delete.return_value = True

    async def perform():
        if operation == "add":
            await call_add(models.ServerCreate(endpoint="", server="synthetic"), server_case.user)
        else:
            await call_delete(70, server_case.user)

    if allowed:
        await perform()
    else:
        with pytest.raises(HTTPException):
            await perform()
        server_case.insert.assert_not_awaited()
        server_case.delete.assert_not_awaited()


@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_stale_delete_is_not_reported_success(server_case, monkeypatch, missing):
    monkeypatch.setattr(
        models.ServerDao,
        "find_server",
        AsyncMock(return_value=None if missing else models.Server(id=70, tenant_id=3, endpoint="", server="synthetic")),
    )
    server_case.delete.return_value = False
    with pytest.raises(HTTPException) as exc:
        await call_delete(70, server_case.user)
    assert exc.value.status_code == 404


async def test_create_schema_has_no_persistence_or_ownership_fields():
    fields = models.ServerCreate.model_fields
    assert not ({"tenant_id", "id", "create_time", "update_time"} & fields.keys())


async def test_delete_dao_preserves_foreign_sqlite_row(monkeypatch):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, create_engine

    engine = create_engine("sqlite://", poolclass=StaticPool)
    models.Server.__table__.create(engine)
    with Session(engine) as session:
        session.add(models.Server(id=70, tenant_id=4, endpoint="", server="synthetic"))
        session.commit()

        class Adapter:
            async def exec(self, statement):
                return session.exec(statement)

            async def commit(self):
                session.commit()

        @asynccontextmanager
        async def cm():
            yield Adapter()

        monkeypatch.setattr(models, "get_async_db_session", cm)
        from bisheng.core.context.tenant import bypass_tenant_filter

        assert await models.ServerDao.delete(70, tenant_id=3) is False
        # Global SELECT hooks may be installed by earlier suites. Inspect the
        # complete local fixture, not visibility through the current tenant.
        with bypass_tenant_filter():
            assert session.get(models.Server, 70) is not None
        assert await models.ServerDao.delete(70, tenant_id=4) is True
        with bypass_tenant_filter():
            assert session.get(models.Server, 70) is None
    engine.dispose()
