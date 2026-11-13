"""Authentication must run on every variable route before any database access."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from bisheng.api.v1 import variable
from bisheng.common.dependencies.user_deps import UserPayload

VARIABLE = {
    "flow_id": "auth-regression-flow",
    "version_id": 1,
    "node_id": "input-node",
    "variable_name": "question",
    "value_type": 1,
    "value": "hello",
}
ROUTES = [
    pytest.param("POST", "/variable/", {"json": VARIABLE}, id="post-variable"),
    pytest.param(
        "GET", "/variable/list", {"params": {"flow_id": VARIABLE["flow_id"], "version_id": 1}}, id="list-variables"
    ),
    pytest.param("DELETE", "/variable/del", {"params": {"id": 1}}, id="delete-variable"),
    pytest.param("POST", "/variable/save_all", {"json": [VARIABLE]}, id="save-all-variables"),
]


@pytest.fixture
def app():
    # Do not add authentication here: it must come from the production router.
    app = FastAPI()
    app.include_router(variable.router)
    return app


def _dependency_calls(dependant):
    yield dependant.call
    for dependency in dependant.dependencies:
        yield from _dependency_calls(dependency)


@pytest.mark.parametrize("method,path,request_kwargs", ROUTES)
def test_variable_route_declares_login_dependency(app, method, path, request_kwargs):
    route = next(
        route for route in app.routes if isinstance(route, APIRoute) and route.path == path and method in route.methods
    )
    assert UserPayload.get_login_user in tuple(_dependency_calls(route.dependant))


@pytest.mark.parametrize("method,path,request_kwargs", ROUTES)
def test_variable_route_executes_login_dependency(app, monkeypatch, method, path, request_kwargs):
    auth_calls = []
    database_calls = []

    async def reject_login():
        auth_calls.append(True)
        raise HTTPException(status_code=401, detail="variable auth regression")

    def reject_database_access(*args, **kwargs):
        # Also keep the vulnerable version safe to test without live middleware.
        database_calls.append(True)
        raise AssertionError("Unauthenticated request reached the database")

    from bisheng.variable.domain.repositories import variable_repository

    monkeypatch.setattr(variable_repository, "get_sync_db_session", reject_database_access)
    app.dependency_overrides[UserPayload.get_login_user] = reject_login

    with TestClient(app) as client:
        response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "variable auth regression"}
    assert auth_calls == [True]
    assert database_calls == []
