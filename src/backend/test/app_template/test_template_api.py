"""Template HTTP contract with real ORM tenant events and a local database."""

import json
from contextlib import asynccontextmanager, contextmanager
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.v1 import skillcenter
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context import tenant
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.permission.application.identity import current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.fixtures.table_definitions import TABLE_ASSISTANT, TABLE_FLOW


@pytest.fixture
async def api(tmp_path, monkeypatch, mock_settings):
    mock_settings.multi_tenant.enabled = True
    db_path = tmp_path / "templates.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text(TABLE_FLOW))
        conn.execute(text(TABLE_ASSISTANT))
        conn.execute(text("ALTER TABLE flow ADD COLUMN is_shared BOOLEAN DEFAULT 0"))
        for column in [
            "guide_word TEXT",
            "guide_question JSON",
            "temperature FLOAT DEFAULT 1",
            "max_token INTEGER DEFAULT 32000",
            "is_shared BOOLEAN DEFAULT 0",
            "knowledge_auth BOOLEAN DEFAULT 0",
        ]:
            conn.execute(text(f"ALTER TABLE assistant ADD COLUMN {column}"))
        conn.execute(
            text("""CREATE TABLE template (
            id INTEGER PRIMARY KEY, name VARCHAR, description VARCHAR, data JSON,
            order_num INTEGER, flow_type INTEGER, flow_id VARCHAR, guide_word VARCHAR,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP, update_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        )
        for tid in (1, 2, 3):
            for kind in (5, 10):
                conn.execute(
                    text(
                        "INSERT INTO template (id,name,data,order_num,flow_type,tenant_id) "
                        "VALUES (:id,:name,:data,65535,:kind,:tid)"
                    ),
                    {
                        "id": tid * 100 + kind,
                        "name": f"tenant-{tid}-{kind}",
                        "data": '{"nodes":[],"edges":[]}',
                        "kind": kind,
                        "tid": tid,
                    },
                )
            conn.execute(
                text("INSERT INTO flow (id,name,user_id,tenant_id,flow_type,data) VALUES (:id,:name,7,:tid,10,:data)"),
                {"id": f"flow-{tid}", "name": "Source", "tid": tid, "data": '{"nodes":[],"edges":[]}'},
            )
            conn.execute(
                text(
                    "INSERT INTO assistant (id,name,user_id,tenant_id,prompt,guide_word,temperature,max_token,is_delete) "
                    "VALUES (:id,:name,7,:tid,:prompt,:guide,0.5,4000,0)"
                ),
                {
                    "id": f"assistant-{tid}",
                    "name": "Source",
                    "tid": tid,
                    "prompt": "Reusable instructions",
                    "guide": "Welcome",
                },
            )
    register_tenant_filter_events()
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    @contextmanager
    def sync_session():
        with Session(engine) as session:
            yield session

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    if hasattr(skillcenter, "get_sync_db_session"):
        monkeypatch.setattr(skillcenter, "get_sync_db_session", sync_session)
    try:
        repo = import_module("bisheng.app_template.domain.repositories.template_repository")
    except ModuleNotFoundError as exc:
        if not exc.name.startswith("bisheng.app_template"):
            raise
    else:
        monkeypatch.setattr(repo, "get_async_db_session", async_session)
    authorization = AsyncMock()
    monkeypatch.setattr("bisheng.permission.application.business_authorization.require_business_action", authorization)
    # Service imports the application protocol; patch that bound symbol if loaded.
    try:
        service = import_module("bisheng.app_template.domain.services.template_service")
    except ModuleNotFoundError as exc:
        if not exc.name.startswith("bisheng.app_template"):
            raise
    else:
        monkeypatch.setattr(service, "require_business_action", authorization)
        monkeypatch.setattr(service, "settings", mock_settings)

    app = FastAPI()
    app.include_router(skillcenter.router, prefix="/api/v1")
    user = SimpleNamespace(user_id=7, tenant_id=2, is_global_super=False)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user

    @app.exception_handler(BaseErrorCode)
    async def domain_error(request: Request, exc: BaseErrorCode):
        return JSONResponse(exc.return_resp_instance().model_dump(), status_code=200)

    bindings = [
        (tenant.current_tenant_id, 2),
        (tenant.visible_tenant_ids, frozenset({1, 2})),
        (tenant._bypass_tenant_filter, False),
        (tenant._strict_tenant_filter, False),
        (tenant._admin_scope_tenant_id, None),
        (tenant._is_management_api, False),
        (current_permission_actor, PermissionActor(user_id=7, tenant_id=2)),
    ]
    tokens = [(var, var.set(value)) for var, value in bindings]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, engine=engine, authorize=authorization, user=user)
    for var, token in reversed(tokens):
        var.reset(token)
    await async_engine.dispose()
    engine.dispose()


def admin(*, super_admin=False, admin_tenants=frozenset({2})):
    current_permission_actor.set(
        PermissionActor(user_id=7, tenant_id=2, super_admin=super_admin, tenant_admin_tenant_ids=admin_tenants)
    )


@pytest.mark.parametrize("kind", [5, 10])
async def test_list_only_current_tenant(api, kind):
    result = (await api.client.get("/api/v1/skill/template", params={"flow_type": kind})).json()
    assert [row["id"] for row in result["data"]] == [200 + kind]


@pytest.mark.parametrize("target", [110, 310, 999])
async def test_other_tenant_and_missing_detail_are_rejected(api, target):
    result = (await api.client.get("/api/v1/skill/template", params={"id": target})).json()
    assert result["status_code"] == 404


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/template/create", {"name": "Unauthorized", "flow_id": "flow-2", "flow_type": 10}),
        ("POST", "/template/210", {"name": "Unauthorized"}),
        ("DELETE", "/template/210", None),
    ],
)
async def test_regular_users_cannot_write(api, method, path, payload):
    result = (await api.client.request(method, "/api/v1/skill" + path, json=payload)).json()
    assert result["status_code"] == 19000


@pytest.mark.parametrize("kind,source", [(10, "flow-2"), (5, "assistant-2")])
async def test_admin_creates_server_snapshot_in_current_tenant(api, kind, source):
    admin()
    result = (
        await api.client.post(
            "/api/v1/skill/template/create",
            json={
                "name": f"New-{kind}",
                "description": "Reusable",
                "flow_type": kind,
                "flow_id": source,
                "tenant_id": 3,
                "id": 999,
                "data": {"prompt": "forged", "nodes": ["forged"]},
            },
        )
    ).json()
    assert result["status_code"] == 200
    row = result["data"]
    assert row["tenant_id"] == 2
    assert row["id"] != 999
    if kind == 5:
        assert row["data"]["prompt"] == "Reusable instructions"
        assert row["data"]["guide_word"] == "Welcome"
        assert "user_id" not in row["data"]
        assert "tenant_id" not in row["data"]
    else:
        assert row["data"] == {"nodes": [], "edges": []}
    api.authorize.assert_awaited_once()


@pytest.mark.parametrize("source", ["flow-1", "flow-3", "missing"])
async def test_admin_cannot_template_other_tenant_source(api, source):
    admin(super_admin=True)
    result = (
        await api.client.post(
            "/api/v1/skill/template/create",
            json={
                "name": "Cross tenant",
                "flow_type": 10,
                "flow_id": source,
            },
        )
    ).json()
    assert result["status_code"] == 404


async def test_unreadable_source_cannot_be_saved(api):
    from bisheng.common.errcode.permission import PermissionDeniedError

    admin()
    api.authorize.side_effect = PermissionDeniedError()
    result = (
        await api.client.post(
            "/api/v1/skill/template/create",
            json={
                "name": "Not permitted",
                "flow_type": 10,
                "flow_id": "flow-2",
            },
        )
    ).json()
    assert result["status_code"] == 19000
    with api.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM template WHERE name='Not permitted'")).scalar() == 0


async def test_same_name_in_other_tenant_does_not_block_create(api):
    admin()
    result = (
        await api.client.post(
            "/api/v1/skill/template/create",
            json={
                "name": "tenant-1-10",
                "flow_type": 10,
                "flow_id": "flow-2",
            },
        )
    ).json()
    assert result["status_code"] == 200
    duplicate = (
        await api.client.post(
            "/api/v1/skill/template/create",
            json={
                "name": "tenant-1-10",
                "flow_type": 10,
                "flow_id": "flow-2",
            },
        )
    ).json()
    assert duplicate["status_code"] == 10530


@pytest.mark.parametrize("super_admin", [False, True])
async def test_admin_updates_and_deletes_only_current_tenant(api, super_admin):
    admin(super_admin=super_admin)
    for target in [110, 310]:
        result = (await api.client.post(f"/api/v1/skill/template/{target}", json={"order_num": 42})).json()
        assert result["status_code"] == 404
        result = (await api.client.delete(f"/api/v1/skill/template/{target}")).json()
        assert result["status_code"] == 404
    result = (await api.client.post("/api/v1/skill/template/210", json={"order_num": 42})).json()
    assert result["data"]["order_num"] == 42
    assert (await api.client.delete("/api/v1/skill/template/210")).json()["status_code"] == 200
    with api.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM template WHERE id IN (110,310)")).scalar() == 2


async def test_admin_of_different_tenant_is_not_current_admin(api):
    admin(admin_tenants=frozenset({3}))
    result = (await api.client.delete("/api/v1/skill/template/210")).json()
    assert result["status_code"] == 19000


async def test_missing_tenant_fails_closed(api):
    tenant.current_tenant_id.set(None)
    admin(super_admin=True)
    result = (await api.client.get("/api/v1/skill/template")).json()
    assert result["status_code"] == 20004


@pytest.mark.parametrize("tid", [1, 2, 3])
async def test_super_admin_reads_only_selected_tenant(api, tid):
    admin(super_admin=True)
    with tenant.management_tenant_scope(tid):
        rows = (await api.client.get("/api/v1/skill/template")).json()["data"]
        assert {row["id"] for row in rows} == {tid * 100 + 5, tid * 100 + 10}


async def test_single_tenant_mode_falls_back_to_default_tenant(api, mock_settings):
    mock_settings.multi_tenant.enabled = False
    tenant.current_tenant_id.set(None)
    rows = (await api.client.get("/api/v1/skill/template")).json()["data"]
    assert {row["id"] for row in rows} == {105, 110}


async def test_report_asset_fallback_is_current_tenant_only(api):
    from bisheng.api.services.report_template import ais_app_template_asset

    with api.engine.begin() as conn:
        for tid in (1, 2, 3):
            data = {
                "nodes": [
                    {
                        "data": {
                            "type": "report",
                            "group_params": [
                                {
                                    "params": [
                                        {
                                            "key": "report_info",
                                            "value": {"version_key": f"report-{tid}"},
                                        }
                                    ]
                                }
                            ],
                        }
                    }
                ]
            }
            conn.execute(
                text("UPDATE template SET data=:data WHERE id=:id"), {"data": json.dumps(data), "id": tid * 100 + 10}
            )
    assert await ais_app_template_asset("report-2")
    assert not await ais_app_template_asset("report-1")
    assert not await ais_app_template_asset("report-3")


async def test_update_cannot_replace_snapshot_or_tenant(api):
    admin()
    result = (
        await api.client.post(
            "/api/v1/skill/template/210",
            json={
                "tenant_id": 3,
                "data": {"nodes": ["forged"]},
                "flow_id": "flow-3",
                "flow_type": 5,
                "name": "Renamed",
            },
        )
    ).json()
    assert result["data"]["tenant_id"] == 2
    assert result["data"]["data"] == {"nodes": [], "edges": []}
    assert result["data"]["flow_type"] == 10


async def test_template_type_must_match_detail(api):
    result = (await api.client.get("/api/v1/skill/template", params={"id": 205, "flow_type": 10})).json()
    assert result["status_code"] == 404


async def test_authorization_failure_is_not_downgraded(api):
    from bisheng.common.errcode.permission import PermissionServiceUnavailableError

    admin()
    api.authorize.side_effect = PermissionServiceUnavailableError()
    result = (
        await api.client.post(
            "/api/v1/skill/template/create",
            json={
                "name": "Unavailable authorization",
                "flow_type": 10,
                "flow_id": "flow-2",
            },
        )
    ).json()
    assert result["status_code"] == 25021


def test_template_paths_participate_in_management_scope():
    from bisheng.common.middleware.admin_scope import _is_management_api_path, requires_expected_management_tenant

    for path in ["/api/v1/skill/template", "/api/v1/skill/template/create", "/api/v1/skill/template/210"]:
        assert _is_management_api_path(path)
    assert requires_expected_management_tenant("POST", "/api/v1/skill/template/create")
    assert requires_expected_management_tenant("POST", "/api/v1/skill/template/210")
    assert requires_expected_management_tenant("DELETE", "/api/v1/skill/template/210")
    assert not requires_expected_management_tenant("GET", "/api/v1/skill/template")


async def test_assistant_creation_uses_selected_tenant_not_jwt_tenant(api, monkeypatch):
    from starlette.requests import Request

    from bisheng.api.v1 import assistant as endpoint
    from bisheng.api.v1.schemas import AssistantCreateReq

    async def persist(request, login_user, assistant):
        with Session(api.engine) as session:
            session.add(assistant)
            session.commit()
            session.refresh(assistant)
            return assistant

    monkeypatch.setattr(endpoint.AssistantService, "create_assistant", persist)
    creator = SimpleNamespace(user_id=7, tenant_id=1, is_global_super=True)
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/assistant", "headers": []})
    with tenant.management_tenant_scope(2):
        await endpoint.create_assistant.__wrapped__(
            request=request, login_user=creator, req=AssistantCreateReq(name="Scoped assistant", prompt="", logo="")
        )
    with api.engine.connect() as conn:
        assert conn.execute(text("SELECT tenant_id FROM assistant WHERE name='Scoped assistant'")).scalar() == 2
