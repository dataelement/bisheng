"""HTTP regressions for variable ownership, tenant boundaries and atomic replacement."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.api.v1 import variable as endpoints
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, visible_tenant_ids
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.variable_value import Variable


def payload(flow_id="a", version_id=11, **kwargs):
    return dict(
        flow_id=flow_id, version_id=version_id, node_id="n1", variable_name="x", value="new", value_type=1, **kwargs
    )


@pytest.fixture()
def harness(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Flow, FlowVersion, Variable):
        model.__table__.create(engine)
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    register_tenant_filter_events()
    with bypass_tenant_filter(), Session(engine) as session:
        session.add_all(
            [
                Flow(id="a", name="A", tenant_id=1),
                Flow(id="b", name="B", tenant_id=1),
                Flow(id="other", name="Other", tenant_id=2),
                Flow(id="legacy", name="Legacy", tenant_id=1, flow_type=5),
                FlowVersion(id=11, flow_id="a", name="v1", tenant_id=1, is_current=1),
                FlowVersion(id=12, flow_id="a", name="v2", tenant_id=1),
                FlowVersion(id=21, flow_id="b", name="v1", tenant_id=1, is_current=1),
                FlowVersion(id=31, flow_id="other", name="v1", tenant_id=2, is_current=1),
                FlowVersion(id=41, flow_id="legacy", name="v1", tenant_id=1, flow_type=5, is_current=1),
                Variable(id=1, **payload(), tenant_id=1),
                Variable(id=2, **payload(version_id=12), tenant_id=1),
                Variable(id=3, **payload("b", 21), tenant_id=1),
                Variable(id=4, **payload("other", 31), tenant_id=2),
            ]
        )
        session.commit()

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    # Patch the persistence boundary, retaining real ORM statements and transactions.
    monkeypatch.setattr(endpoints, "get_sync_db_session", session_factory, raising=False)
    monkeypatch.setattr("bisheng.database.models.variable_value.get_sync_db_session", session_factory)
    monkeypatch.setattr("bisheng.database.models.flow_version.get_sync_db_session", session_factory)
    try:
        from bisheng.variable.domain.repositories import variable_repository
    except ModuleNotFoundError:
        pass
    else:
        monkeypatch.setattr(variable_repository, "get_sync_db_session", session_factory)
    allowed = {"a"}
    calls = []

    async def authorize(user, *, resource_type, resource_id, action):
        calls.append((resource_type, resource_id, action))
        if resource_id not in allowed:
            raise UnAuthorizedError()

    # Patch only the external permission decision, not business ownership validation.
    import bisheng.permission.application.business_authorization as authorization

    monkeypatch.setattr(authorization, "require_business_action", authorize)
    try:
        from bisheng.variable.domain.services import variable_service
    except ModuleNotFoundError:
        pass
    else:
        monkeypatch.setattr(variable_service, "require_business_action", authorize)

    async def user():
        return SimpleNamespace(user_id=7, tenant_id=1)

    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = user

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"status_code": exc.code})

    tid = current_tenant_id.set(1)
    visible = visible_tenant_ids.set(frozenset({1, 2}))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield SimpleNamespace(client=client, engine=engine, allowed=allowed, calls=calls)
    finally:
        visible_tenant_ids.reset(visible)
        current_tenant_id.reset(tid)
        engine.dispose()


def snapshot(h):
    with bypass_tenant_filter(), Session(h.engine) as session:
        return [
            (v.id, v.flow_id, v.version_id, v.tenant_id, v.value)
            for v in session.exec(select(Variable).order_by(Variable.id)).all()
        ]


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/list?flow_id=b&version_id=21", None),
        ("POST", "/", payload("b", 21, id=3)),
        ("DELETE", "/del?id=3", None),
        ("POST", "/save_all", [payload("b", 21)]),
    ],
)
def test_no_permission_denies_without_changes(harness, method, path, body):
    before = snapshot(harness)
    response = harness.client.request(method, "/api/v1/variable" + path, json=body)
    assert response.status_code == 403
    assert snapshot(harness) == before


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/list?flow_id=other&version_id=31", None),
        ("POST", "/", payload("other", 31, id=4)),
        ("DELETE", "/del?id=4", None),
        ("POST", "/save_all", [payload("other", 31)]),
    ],
)
def test_cross_tenant_denies_even_when_permission_facade_allows(harness, method, path, body):
    harness.allowed.add("other")
    before = snapshot(harness)
    response = harness.client.request(method, "/api/v1/variable" + path, json=body)
    assert response.status_code in (403, 404)
    assert snapshot(harness) == before


@pytest.mark.parametrize("body", [[], [payload(), payload("b", 21)], [payload(), payload(version_id=12)]])
def test_invalid_batch_is_rejected_before_delete(harness, body):
    before = snapshot(harness)
    response = harness.client.post("/api/v1/variable/save_all", json=body)
    assert response.status_code in (400, 422)
    assert snapshot(harness) == before


def test_replace_preserves_other_versions_and_tenants(harness):
    response = harness.client.post("/api/v1/variable/save_all", json=[payload()])
    assert response.status_code == 200
    rows = snapshot(harness)
    assert len(rows) == 4
    assert {(v[0], v[2], v[3]) for v in rows if v[2] != 11} == {(2, 12, 1), (3, 21, 1), (4, 31, 2)}
    assert ("workflow", "a", "edit") in harness.calls


def test_failed_replacement_rolls_back_delete(harness):
    before = snapshot(harness)

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO T_VARIABLE_VALUE"):
            raise RuntimeError("simulated insertion failure")

    event.listen(harness.engine, "before_cursor_execute", fail_insert)
    try:
        response = harness.client.post("/api/v1/variable/save_all", json=[payload()])
    finally:
        event.remove(harness.engine, "before_cursor_execute", fail_insert)
    assert snapshot(harness) == before
    assert response.status_code == 500


@pytest.mark.parametrize(
    "path", ["/list?flow_id=a&version_id=21", "/list?flow_id=legacy&version_id=41", "/list?flow_id=a&version_id=0"]
)
def test_invalid_read_target_is_rejected(harness, path):
    assert harness.client.get("/api/v1/variable" + path).status_code in (400, 404, 422)


def test_update_cannot_launder_foreign_id_through_authorized_flow(harness):
    before = snapshot(harness)
    response = harness.client.post("/api/v1/variable/", json=payload(id=3))
    assert response.status_code in (400, 403, 404)
    assert snapshot(harness) == before


def test_request_cannot_choose_tenant(harness):
    before = snapshot(harness)
    response = harness.client.post("/api/v1/variable/", json=payload(tenant_id=2))
    assert response.status_code == 422
    assert snapshot(harness) == before


def test_visible_read_returns_only_verified_version(harness):
    response = harness.client.get("/api/v1/variable/list?flow_id=a")
    assert response.status_code == 200
    assert [v["id"] for v in response.json()["data"]] == [1]
    assert harness.calls == [("workflow", "a", "visible")]


def test_authorized_create_update_delete(harness):
    body = dict(payload(), variable_name="second")
    response = harness.client.post("/api/v1/variable/", json=body)
    assert response.status_code == 200
    variable_id = response.json()["data"]["id"]
    body.update(id=variable_id, value="changed")
    assert harness.client.post("/api/v1/variable/", json=body).json()["data"]["value"] == "changed"
    assert harness.client.delete(f"/api/v1/variable/del?id={variable_id}").status_code == 200
    assert {row[0] for row in snapshot(harness)} == {1, 2, 3, 4}
    assert harness.calls == [("workflow", "a", "edit")] * 3


@pytest.mark.parametrize("mutation", ["deleted_flow", "deleted_version", "online_current"])
def test_uneditable_targets_preserve_variables(harness, mutation):
    with bypass_tenant_filter(), Session(harness.engine) as session:
        if mutation == "deleted_flow":
            session.get(Flow, "a").is_delete = 1
        elif mutation == "deleted_version":
            session.get(FlowVersion, 11).is_delete = 1
        else:
            session.get(Flow, "a").status = 2
        session.commit()
    before = snapshot(harness)
    response = harness.client.post("/api/v1/variable/save_all", json=[payload()])
    assert response.status_code in (403, 404)
    assert snapshot(harness) == before


def test_online_noncurrent_version_can_be_edited(harness):
    with bypass_tenant_filter(), Session(harness.engine) as session:
        session.get(Flow, "a").status = 2
        session.commit()
    response = harness.client.post("/api/v1/variable/", json=payload(version_id=12, id=2))
    assert response.status_code == 200


def test_missing_tenant_context_refuses_delete(harness):
    before = snapshot(harness)
    token = current_tenant_id.set(None)
    try:
        response = harness.client.delete("/api/v1/variable/del?id=1")
    finally:
        current_tenant_id.reset(token)
    assert response.status_code == 403
    assert snapshot(harness) == before


def test_permission_failure_restores_strict_context(harness):
    from bisheng.core.context.tenant import is_strict_tenant_filter

    assert not is_strict_tenant_filter()
    assert harness.client.delete("/api/v1/variable/del?id=3").status_code == 403
    assert not is_strict_tenant_filter()


def test_update_cannot_move_node(harness):
    before = snapshot(harness)
    body = dict(payload(id=1), node_id="different")
    assert harness.client.post("/api/v1/variable/", json=body).status_code == 400
    assert snapshot(harness) == before


def test_duplicate_name_does_not_create_row(harness):
    before = snapshot(harness)
    assert harness.client.post("/api/v1/variable/", json=payload()).status_code == 409
    assert snapshot(harness) == before
