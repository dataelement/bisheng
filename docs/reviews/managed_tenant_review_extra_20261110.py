"""Additional observation probes; assertions describe defects, not acceptance."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from managed_tenant_investigation_20261110_repro import admin, managed_scope
from managed_tenant_investigation_20261110_repro import database as database
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient
from sqlmodel import select
from bisheng.core.context import tenant
from bisheng.database.models.role_access import RoleAccess
from bisheng.database.models.user_role import UserRole
from bisheng.role.domain.services.role_service import RoleService
from bisheng.role.domain.services.quota_service import QuotaService, require_quota
from test.app_publish.conftest import _sqlite_ddl_quirks


async def create_table(database, table):
    with _sqlite_ddl_quirks([table]):
        async with database() as session:
            connection = await session.connection()
            await connection.run_sync(table.create)
            await session.commit()


async def test_menu_helper_assigns_global_menu_to_view_tenant(database):
    await create_table(database, RoleAccess.__table__)
    with managed_scope():
        async with database() as session:
            await RoleService._replace_menu_access_in_session(session, 2, ["tool"])
            await session.commit()
    with tenant.bypass_tenant_filter():
        async with database() as session:
            row = (await session.exec(select(RoleAccess))).one()
            assert row.role_id == 2 and row.tenant_id == 2  # Global role is tenant 1.


async def test_batch_catalog_wrong_without_management_scope(database, monkeypatch):
    import bisheng.department.domain.services.department_service as module

    monkeypatch.setattr(module, "get_async_db_session", database)
    monkeypatch.setattr(module, "_can_access_dept", AsyncMock(return_value=True))
    dept = SimpleNamespace(id=20, dept_id="child", tenant_id=2, path="/20/")
    with tenant.tenant_execution_scope(1):
        assert not tenant.get_is_management_api()
        catalog = await module.DepartmentService._aget_assignable_roles_catalog(
            [dept], admin()
        )
    assert {r["id"] for r in catalog["child"]} == {2, 3}  # Missing tenant-2 role 4.


async def test_nonadmin_creation_quota_http_uses_real_binding(database, monkeypatch):
    import bisheng.user.domain.models.user_role as binding_module
    import bisheng.common.middleware.admin_scope as middleware
    import bisheng.admin.application.tenant_scope as scope_module

    await create_table(database, UserRole.__table__)
    monkeypatch.setattr(binding_module, "get_async_db_session", database)
    with tenant.bypass_tenant_filter():
        async with database() as session:
            session.add(UserRole(id=1, user_id=77, role_id=2, tenant_id=2))
            await session.commit()
    monkeypatch.setattr(
        QuotaService,
        "_apply_tenant_chain_cap",
        AsyncMock(side_effect=lambda q, *_: (q, None)),
    )
    monkeypatch.setattr(
        QuotaService, "get_user_resource_count", AsyncMock(return_value=0)
    )
    user = SimpleNamespace(user_id=77, tenant_id=2, is_admin=lambda: False)
    monkeypatch.setattr(middleware, "_decode_jwt_subject", lambda _: {"user_id": 77})
    monkeypatch.setattr(
        middleware, "_check_is_global_super", AsyncMock(return_value=False)
    )
    resolver = AsyncMock(
        return_value=scope_module.EffectiveManagementScope(2, "own", None)
    )
    monkeypatch.setattr(scope_module, "resolve_management_scope", resolver)
    app = FastAPI()
    app.add_middleware(middleware.AdminScopeMiddleware)

    async def login():
        return user

    @app.post("/api/v1/workflow/create")
    @require_quota("channel")
    async def probe(login_user=Depends(login)):
        return {"created": True}

    # A minimal HTTP creation probe exercises the production middleware and decorator.
    # It deliberately uses channel quota because the seeded global role config is channel=0.
    with tenant.tenant_execution_scope(2):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://probe"
        ) as client:
            client.cookies.set("access_token_cookie", "probe")
            response = await client.post(
                "/api/v1/workflow/create", headers={"X-Management-Tenant": "2"}
            )
    assert response.status_code == 200 and response.json() == {"created": True}
    resolver.assert_awaited_once_with(77, is_super=False, for_write=True)
    assert (
        QuotaService._apply_tenant_chain_cap.await_args.args[0] == 10
    )  # Bound role says 0.


async def test_qa_projection_failure_persists_copying_source_and_target(
    database, monkeypatch
):
    import bisheng.knowledge.domain.models.knowledge as model
    import bisheng.knowledge.domain.services.knowledge_service as module

    await create_table(database, model.Knowledge.__table__)
    monkeypatch.setattr(model, "get_async_db_session", database)
    monkeypatch.setattr(
        module.KnowledgeService,
        "_load_library_permission_record",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        module.KnowledgeService,
        "_project_library_copy",
        AsyncMock(side_effect=RuntimeError("projection failed")),
    )
    source = model.Knowledge(
        id=10, name="QA source", tenant_id=2, user_id=7, type=1, state=1
    )
    with managed_scope():
        async with database() as session:
            session.add(source)
            await session.commit()
        import pytest

        with pytest.raises(RuntimeError, match="projection failed"):
            await module.KnowledgeService.copy_qa_knowledge(None, admin(), source)
        async with database() as session:
            rows = (
                await session.exec(select(model.Knowledge).order_by(model.Knowledge.id))
            ).all()
            assert len(rows) == 2
            assert rows[0].id == 10 and rows[0].state == 2
            assert rows[1].tenant_id == 2 and rows[1].state == 0
