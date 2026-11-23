"""Diagnostic assertions for current bugs, not acceptance tests for fixed code.

Run from src/backend with PYTHONPATH=. and config pointing to a temporary {} YAML:
python -m pytest /path/to/managed_tenant_repro.py --asyncio-mode=auto -p no:cacheprovider -q
Only in-memory SQLite and mocked external services are used.
"""
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test.fixtures.mock_services import premock_import_chain
premock_import_chain()

from sqlalchemy import create_engine
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession
from bisheng.core.context import tenant
from bisheng.core.database import tenant_filter
from bisheng.database.models.role import Role, RoleDao
from bisheng.role.domain.services.role_service import RoleService
from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
from bisheng.common.errcode.role import RoleNotFoundError
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.tool.domain.models.gpts_tools import GptsToolsType, GptsToolsTypeRead, GptsToolsDao
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.flow_version import FlowVersion
from test.app_publish.conftest import _sqlite_ddl_quirks


@contextmanager
def managed_scope():
    token = tenant.current_tenant_id.set(1)
    try:
        with tenant.management_tenant_scope(2):
            yield
    finally:
        tenant.current_tenant_id.reset(token)


@pytest.fixture
async def database(monkeypatch):
    import bisheng.database.models.role as role_module
    import bisheng.role.domain.services.role_service as role_service_module
    import bisheng.tool.domain.models.gpts_tools as tool_module
    tenant_filter.register_tenant_filter_events()
    engine = create_async_engine('sqlite+aiosqlite://')
    tables = [Role.__table__, GptsToolsType.__table__]
    with _sqlite_ddl_quirks(tables):
        async with engine.begin() as conn:
            for table in tables:
                await conn.run_sync(table.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    for module in (role_module, role_service_module, tool_module):
        monkeypatch.setattr(module, 'get_async_db_session', sessions)
    with tenant.bypass_tenant_filter():
        async with sessions() as session:
            session.add(Role(id=2, role_name='global', role_type='global', tenant_id=1,
                             quota_config={'channel': 0}))
            session.add(Role(id=3, role_name='root custom', role_type='tenant', tenant_id=1))
            session.add(Role(id=4, role_name='child custom', role_type='tenant', tenant_id=2))
            await session.commit()
    yield sessions
    await engine.dispose()


def admin():
    return SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True)


@pytest.mark.parametrize('operation', ['update_role_with_menu', 'update_menu'])
async def test_global_role_second_lookup_fails(database, monkeypatch, operation):
    monkeypatch.setattr(RoleService, '_check_role_permission', AsyncMock())
    monkeypatch.setattr(RoleService, '_ensure_role_mutation_access', AsyncMock())
    with managed_scope():
        assert await RoleDao.aget_role_by_id(2) is not None
        with pytest.raises(RoleNotFoundError):
            if operation == 'update_menu':
                await RoleService.update_menu(2, [], admin())
            else:
                await RoleService.update_role_with_menu(2, RoleUpdateRequest(remark='changed'), admin())


async def test_role_update_commits_before_refresh_failure(database, monkeypatch):
    monkeypatch.setattr(RoleService, '_check_role_permission', AsyncMock())
    monkeypatch.setattr(RoleService, '_ensure_role_mutation_access', AsyncMock())
    with managed_scope():
        with pytest.raises(InvalidRequestError, match='refresh'):
            await RoleService.update_role(2, RoleUpdateRequest(remark='persisted despite failure'), admin())
    with tenant.bypass_tenant_filter():
        assert (await RoleDao.aget_role_by_id(2)).remark == 'persisted despite failure'


async def test_quota_zero_disappears_when_global_role_is_filtered(database, monkeypatch):
    import bisheng.role.domain.services.quota_service as module
    monkeypatch.setattr(module.UserRoleDao, 'aget_user_roles', AsyncMock(return_value=[SimpleNamespace(role_id=2)]))
    monkeypatch.setattr(QuotaService, '_apply_tenant_cap', AsyncMock(side_effect=lambda value, *_: value))
    token = tenant.current_tenant_id.set(1)
    try:
        with tenant.bypass_tenant_filter():
            assert (await RoleDao.aget_role_by_ids([2]))[0].quota_config['channel'] == 0
            assert await QuotaService.get_effective_quota(7, 'channel', 1) == 0
        with tenant.management_tenant_scope(2):
            assert await RoleDao.aget_role_by_ids([2]) == []
            assert await QuotaService.get_effective_quota(7, 'channel', 1) == 10
    finally:
        tenant.current_tenant_id.reset(token)


@pytest.mark.parametrize('kind', [0, 2])
async def test_tool_wrong_tenant_persists_before_refresh_failure(database, monkeypatch, kind):
    import bisheng.tool.domain.services.tool as module
    user = module.UserPayload(user_id=7, user_name='diagnostic', tenant_id=1, user_role=[1])
    service = module.ToolServices(login_user=user)
    monkeypatch.setattr(service.__class__, 'parse_openapi_schema', AsyncMock())
    monkeypatch.setattr(service.__class__, 'parse_mcp_schema', AsyncMock())
    monkeypatch.setattr(GptsToolsDao, 'get_one_tool_type_by_name', AsyncMock(return_value=None))
    hook = AsyncMock()
    monkeypatch.setattr(service.__class__, 'add_gpts_tools_hook', hook)
    request = GptsToolsTypeRead(name='diagnostic tool', is_preset=kind, children=[])
    with managed_scope():
        with pytest.raises(InvalidRequestError, match='refresh'):
            await service.add_tools(request)
    assert request.tenant_id == 1
    hook.assert_not_awaited()
    with tenant.bypass_tenant_filter():
        async with database() as session:
            rows = (await session.exec(select(GptsToolsType))).all()
            assert len(rows) == 1 and rows[0].tenant_id == 1


def test_workflow_wrong_tenant_persists_before_refresh_failure(monkeypatch):
    import bisheng.database.models.flow as module
    tenant_filter.register_tenant_filter_events()
    engine = create_engine('sqlite://')
    with _sqlite_ddl_quirks([Flow.__table__, FlowVersion.__table__]):
        Flow.__table__.create(engine)
        FlowVersion.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(module, 'get_sync_db_session', sessions)
    flow = Flow(id='diagnostic-flow', name='diagnostic', user_id=7, tenant_id=1, flow_type=10)
    try:
        with managed_scope():
            with pytest.raises(InvalidRequestError, match='refresh'):
                FlowDao.create_flow(flow, 10)
        with tenant.bypass_tenant_filter(), sessions() as session:
            assert session.exec(select(Flow)).one().tenant_id == 1
            assert session.exec(select(FlowVersion)).one().tenant_id == 2
    finally:
        engine.dispose()


async def test_department_role_candidates_use_login_tenant(database, monkeypatch):
    import bisheng.department.domain.services.department_service as module
    monkeypatch.setattr(module, 'get_async_db_session', database)
    dept = SimpleNamespace(id=20, tenant_id=2, parent_id=None)
    monkeypatch.setattr(module, '_get_dept_and_check_permission', AsyncMock(return_value=dept))
    monkeypatch.setattr(module.DepartmentService, '_aget_ancestor_chain_ids', AsyncMock(return_value=[20]))
    with managed_scope():
        rows = await module.DepartmentService.aget_assignable_roles('child-dept', admin())
    ids = {row['id'] for row in rows}
    assert 3 in ids and 4 not in ids


async def test_knowledge_copy_failure_leaves_source_and_target(monkeypatch):
    import bisheng.knowledge.domain.services.knowledge_service as module
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    KnowledgeState = module.KnowledgeState
    source = Knowledge(id=10, name='diagnostic source', tenant_id=2, user_id=7)
    states, targets = {}, []

    async def set_state(ident, state, **_kwargs):
        states[ident] = state

    def create(_request, user, target, skip_hook):
        assert skip_hook is True
        target.id = 11
        target.tenant_id = user.tenant_id
        targets.append(target)
        return target

    failure = RuntimeError('simulated permission projection failure')
    monkeypatch.setattr(module.KnowledgeService, '_load_library_permission_record', AsyncMock(return_value=object()))
    monkeypatch.setattr(module.KnowledgeDao, 'async_update_state', AsyncMock(side_effect=set_state))
    monkeypatch.setattr(module.KnowledgeService, 'create_knowledge_base', create)
    monkeypatch.setattr(module.KnowledgeService, '_project_library_copy', AsyncMock(side_effect=failure))
    with managed_scope(), pytest.raises(RuntimeError, match='simulated permission'):
        await module.KnowledgeService.copy_knowledge(None, None, admin(), source)
    assert states[10] == KnowledgeState.COPYING
    assert len(targets) == 1 and targets[0].tenant_id == 1


async def test_knowledge_copy_real_insert_refresh_leaves_target(monkeypatch):
    import bisheng.knowledge.domain.services.knowledge_service as module
    import bisheng.knowledge.domain.models.knowledge as model
    from sqlalchemy.pool import StaticPool
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    with _sqlite_ddl_quirks([model.Knowledge.__table__]):
        model.Knowledge.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(model, 'get_sync_db_session', sessions)
    source = model.Knowledge(id=10, name='diagnostic source', tenant_id=2, user_id=7)
    states = {}

    async def set_state(ident, state, **_kwargs):
        states[ident] = state

    monkeypatch.setattr(module.KnowledgeService, '_load_library_permission_record', AsyncMock(return_value=object()))
    monkeypatch.setattr(module.KnowledgeDao, 'async_update_state', AsyncMock(side_effect=set_state))
    try:
        with managed_scope(), pytest.raises(InvalidRequestError, match='refresh'):
            await module.KnowledgeService.copy_knowledge(None, None, admin(), source)
        assert states[10] == module.KnowledgeState.COPYING
        with tenant.bypass_tenant_filter(), sessions() as session:
            target = session.exec(select(model.Knowledge)).one()
            assert target.tenant_id == 1 and target.name == 'diagnostic source Copy'
    finally:
        engine.dispose()
