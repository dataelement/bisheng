"""Actual ORM and manual UNION filtering under the browser management view."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from bisheng.common.middleware import admin_scope
from bisheng.core.context import tenant
from bisheng.core.database import tenant_filter


class ManagementViewProbe(SQLModel, table=True):
    id: int = Field(primary_key=True)
    tenant_id: int


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/knowledge",
        "/api/v1/workflow/list",
        "/api/v1/apps",
        "/api/v1/approval/admin/exceptions",
        "/api/v1/audit",
        "/api/v1/app-runtime-audit",
        "/api/v1/roles",
        "/api/v1/permissions",
        "/api/v1/user-groups",
    ],
)
@pytest.mark.parametrize("super_admin,scope,expected", [(False, "3", [2]), (True, "3", [3]), (True, None, [1, 2, 3])])
def test_same_view_filters_orm_and_manual_queries(monkeypatch, path, super_admin, scope, expected):
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {ManagementViewProbe.__tablename__}
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ManagementViewProbe.__table__.create(engine)
    with tenant.bypass_tenant_filter(), Session(engine) as db:
        db.add_all([ManagementViewProbe(id=i, tenant_id=i) for i in (1, 2, 3)])
        db.commit()
    monkeypatch.setattr(admin_scope, "_decode_jwt_subject", lambda _: {"user_id": 7, "tenant_id": 2})
    monkeypatch.setattr(admin_scope, "_check_is_global_super", AsyncMock(return_value=super_admin))
    redis = SimpleNamespace(aget=AsyncMock(return_value=scope), aexpire_key=AsyncMock())
    monkeypatch.setattr(admin_scope, "get_redis_client", AsyncMock(return_value=redis))
    app = FastAPI()
    app.add_middleware(admin_scope.AdminScopeMiddleware)

    @app.get(path)
    def rows():
        with Session(engine) as db:
            automatic = db.exec(select(ManagementViewProbe.id)).all()
            clause = tenant_filter.build_tenant_filter_clause(ManagementViewProbe.tenant_id)
            stmt = select(ManagementViewProbe.id)
            if clause is not None:
                stmt = stmt.where(clause)
            manual = db.exec(stmt).all()
        return {"automatic": automatic, "manual": manual}

    try:
        with tenant.tenant_execution_scope(2), TestClient(app) as client:
            client.cookies.set("access_token_cookie", "test-token")
            assert client.get(path).json() == {"automatic": expected, "manual": expected}
            assert not tenant.is_management_all_tenants()
        if not super_admin:
            redis.aget.assert_not_called()
    finally:
        engine.dispose()


def test_prefix_boundaries_exclude_business_and_rpc_routes():
    for path in [
        "/api/v1/apps-internal/operations",
        "/api/v2/apps/deploy",
        "/api/v1/chat/completions",
        "/api/v1/approval/my-tasks",
    ]:
        assert not admin_scope._is_management_api_path(path)
