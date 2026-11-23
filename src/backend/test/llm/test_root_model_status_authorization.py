"""Root-shared models are readable, never child-admin writable."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bisheng.llm.domain.models import llm_server as dao_module
from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.services import llm as module


@pytest.fixture
def model_case(monkeypatch):
    model = LLMModel(id=701, server_id=70, tenant_id=1, model_name="synthetic", model_type="llm", online=True)
    server = LLMServer(id=70, tenant_id=1, name="synthetic", type="openai")
    user = SimpleNamespace(user_id=33, tenant_id=3)
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(dao_module, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(module, "_check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(dao_module, "_check_is_global_super", AsyncMock(return_value=False))
    from bisheng import permission

    monkeypatch.setattr(permission.application, "is_tenant_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(return_value=model))
    monkeypatch.setattr(LLMDao, "aget_server_by_id", AsyncMock(return_value=server))
    online = AsyncMock()
    status = MagicMock()
    probe = AsyncMock()
    monkeypatch.setattr(LLMDao, "aupdate_model_online", online)
    monkeypatch.setattr(LLMDao, "update_model_status", status)
    monkeypatch.setattr(module.LLMService, "_invoke_model_probe", probe)
    invalidate = MagicMock()
    monkeypatch.setattr(module, "invalidate_llm_info_cache", invalidate)
    monkeypatch.setattr(module.ContextWindowService, "invalidate", AsyncMock())
    return SimpleNamespace(
        model=model, server=server, user=user, online=online, status=status, probe=probe, invalidate=invalidate
    )


@pytest.mark.parametrize("operation", ["online", "verify"])
@pytest.mark.parametrize("owner", [1, 4])
async def test_child_admin_cannot_write_root_or_other_tenant(model_case, operation, owner):
    case = model_case
    case.model.tenant_id = case.server.tenant_id = owner
    with pytest.raises(HTTPException):
        if operation == "online":
            await module.LLMService.update_model_online(701, False, case.user)
        else:
            await module.LLMService.verify_model_status(701, case.user)
    assert case.model.online is True
    case.online.assert_not_awaited()
    case.status.assert_not_called()
    case.probe.assert_not_awaited()
    case.invalidate.assert_not_called()


@pytest.mark.parametrize("operation", ["online", "verify"])
@pytest.mark.parametrize("mismatch", ["server_missing", "server_owner", "server_id"])
async def test_model_parent_mismatch_denied_before_effects(model_case, monkeypatch, operation, mismatch):
    case = model_case
    case.model.tenant_id = case.server.tenant_id = 3
    if mismatch == "server_missing":
        monkeypatch.setattr(LLMDao, "aget_server_by_id", AsyncMock(return_value=None))
    elif mismatch == "server_owner":
        case.server.tenant_id = 1
    else:
        case.server.id = 71
    with pytest.raises(HTTPException):
        if operation == "online":
            await module.LLMService.update_model_online(701, False, case.user)
        else:
            await module.LLMService.verify_model_status(701, case.user)
    case.online.assert_not_awaited()
    case.probe.assert_not_awaited()
    case.status.assert_not_called()


@pytest.fixture
def native_model_scope(tenant_context):
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    # Set ContextVars in the test's synchronous context, not an async fixture's
    # task-local copy, and make isolated/combined runs use the same real filter.
    tenant_context(3)
    register_tenant_filter_events()


@pytest.fixture
async def native_model_db(monkeypatch, tmp_path, native_model_scope):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import Session, create_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan

    path = tmp_path / "model-write.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    for table in (LLMServer.__table__, LLMModel.__table__, KnowledgeOperationPlan.__table__):
        table.create(engine)
    with Session(engine) as session:
        session.add(LLMServer(id=70, tenant_id=3, name="synthetic", type="openai"))
        session.add(LLMModel(id=701, tenant_id=3, server_id=70, model_name="synthetic", model_type="llm", online=True))
        session.commit()
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    statements = []

    def record(_conn, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    event.listen(async_engine.sync_engine, "before_cursor_execute", record)

    @contextmanager
    def sync_session():
        with Session(engine) as session:
            yield session

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine) as session:
            yield session

    monkeypatch.setattr(dao_module, "get_sync_db_session", sync_session)
    monkeypatch.setattr(dao_module, "get_async_db_session", async_session)
    try:
        yield SimpleNamespace(engine=engine, statements=statements)
    finally:
        await async_engine.dispose()
        engine.dispose()


@pytest.mark.parametrize(
    "method,args", [("aupdate_model_online", (701, False)), ("update_model_status", (701, 1, "synthetic"))]
)
async def test_verified_write_sql_binds_model_tenant_and_server(native_model_db, method, args):
    from sqlmodel import Session

    call = getattr(LLMDao, method)(*args, tenant_id=3, server_id=70)
    if method.startswith("a"):
        await call
    updates = [(sql, params) for sql, params in native_model_db.statements if sql.startswith("UPDATE llm_model")]
    assert len(updates) == 1
    sql, parameters = updates[0]
    assert "llm_model.tenant_id = ?" in sql
    assert "llm_model.server_id = ?" in sql
    assert "llm_model.id = ?" in sql
    assert tuple(parameters[-3:]) == (701, 3, 70)
    with Session(native_model_db.engine) as session:
        model = session.get(LLMModel, 701)
        if method == "aupdate_model_online":
            assert model.online is False
        else:
            assert model.status == 1 and model.remark == "synthetic"


@pytest.mark.parametrize("operation", ["online", "verify"])
@pytest.mark.parametrize("scope,is_super", [(3, False), (1, True)])
async def test_own_child_admin_and_root_super_can_write(model_case, monkeypatch, operation, scope, is_super):
    case = model_case
    case.model.tenant_id = case.server.tenant_id = scope
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: scope)
    monkeypatch.setattr(module, "_check_is_global_super", AsyncMock(return_value=is_super))
    if operation == "online":
        await module.LLMService.update_model_online(701, False, case.user)
        case.online.assert_awaited_once_with(701, False, tenant_id=scope, server_id=70)
    else:
        await module.LLMService.verify_model_status(701, case.user)
        case.probe.assert_awaited_once()
        case.status.assert_called_once_with(701, 0, "", tenant_id=scope, server_id=70)


@pytest.mark.parametrize("operation", ["online", "verify"])
async def test_root_regular_admin_cannot_write(model_case, monkeypatch, operation):
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 1)
    with pytest.raises(HTTPException):
        if operation == "online":
            await module.LLMService.update_model_online(701, False, model_case.user)
        else:
            await module.LLMService.verify_model_status(701, model_case.user)
    model_case.probe.assert_not_awaited()
    model_case.online.assert_not_awaited()


async def test_router_preserves_online_actor(model_case):
    from bisheng.llm.api.router import update_model_online

    model_case.model.tenant_id = model_case.server.tenant_id = 3
    await update_model_online(MagicMock(), model_case.user, 701, False)
    model_case.online.assert_awaited_once_with(701, False, tenant_id=3, server_id=70)


@pytest.mark.parametrize("scope,is_super", [(None, False), (None, True), (3, True)])
async def test_missing_scope_or_child_scoped_super_cannot_change_root(model_case, monkeypatch, scope, is_super):
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: scope)
    monkeypatch.setattr(module, "_check_is_global_super", AsyncMock(return_value=is_super))
    with pytest.raises(HTTPException):
        await module.LLMService.verify_model_status(701, model_case.user)
    model_case.probe.assert_not_awaited()
    model_case.status.assert_not_called()


async def test_own_child_non_admin_cannot_write(model_case, monkeypatch):
    from bisheng.permission import application

    model_case.model.tenant_id = model_case.server.tenant_id = 3
    monkeypatch.setattr(application, "is_tenant_admin", AsyncMock(return_value=False))
    with pytest.raises(HTTPException):
        await module.LLMService.update_model_online(701, False, model_case.user)
    model_case.online.assert_not_awaited()


@pytest.mark.parametrize("error", [RuntimeError("synthetic provider unavailable"), TimeoutError()])
async def test_failed_probe_status_write_keeps_verified_scope(model_case, error):
    model_case.model.tenant_id = model_case.server.tenant_id = 3
    model_case.probe.side_effect = error
    await module.LLMService.verify_model_status(701, model_case.user)
    assert model_case.status.call_args.args[:2] == (701, 1)
    assert model_case.status.call_args.kwargs == {"tenant_id": 3, "server_id": 70}


async def test_online_sql_does_not_update_foreign_model_after_parent_change(native_model_db):
    from sqlmodel import Session

    with Session(native_model_db.engine) as session:
        model = session.get(LLMModel, 701)
        model.tenant_id = 1
        session.add(model)
        session.commit()
    from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
    from bisheng.core.context.tenant import get_current_tenant_id

    assert get_current_tenant_id() == 3
    # With the real tenant filter active the stale owner is rejected by the
    # provider guard even before the scoped UPDATE. The foreign row stays intact.
    native_model_db.statements.clear()
    with pytest.raises(LLMModelNotAccessibleError):
        await LLMDao.aupdate_model_online(701, False, tenant_id=3, server_id=70)
    assert not any(sql.startswith("UPDATE llm_model") for sql, _ in native_model_db.statements)
    with Session(native_model_db.engine) as session:
        from bisheng.core.context.tenant import bypass_tenant_filter

        with bypass_tenant_filter():
            assert session.get(LLMModel, 701).online is True
