"""Office callbacks own signature authentication, not browser admission."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from bisheng.admin.application import request_admission
from bisheng.common.request_scope import RequestScope, ScopedAPIRouter, scope_overrides


def _composition_overrides():
    """Use exact production route declarations without importing the whole app."""
    path = Path(__file__).resolve().parents[2] / "bisheng/api/router.py"
    tree = ast.parse(path.read_text())
    calls = []
    for node in tree.body:
        value = node.value if isinstance(node, ast.Expr) else None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "scope_overrides":
            if isinstance(value.args[0], ast.Name) and value.args[0].id in {"report_router", "workflow_router"}:
                calls.append(node)
    return calls


@pytest.mark.parametrize(
    "router_name,endpoint_name", [("report_router", "callback"), ("workflow_router", "upload_report_file")]
)
def test_credential_callback_does_not_require_browser_session(monkeypatch, router_name, endpoint_name):
    router = ScopedAPIRouter()

    async def callback():
        return {"error": 1}  # The endpoint's own signature guard still rejects unsigned data.

    callback.__name__ = endpoint_name
    router.add_api_route("/callback", callback, methods=["POST"])
    namespace = {
        "scope_overrides": scope_overrides,
        "S": RequestScope,
        "report_router": router,
        "workflow_router": router,
    }
    calls = [node for node in _composition_overrides() if node.value.args[0].id == router_name]
    exec(compile(ast.Module(body=calls, type_ignores=[]), "production-scope-declarations", "exec"), namespace)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    parent = ScopedAPIRouter()
    parent.include_router(router, request_scope=RequestScope.TENANT)
    app.include_router(parent)
    browser_auth = AsyncMock(side_effect=HTTPException(401, "Browser session absent"))
    monkeypatch.setattr(request_admission, "authenticate_browser", browser_auth)
    request_admission.install_request_admission(app)
    response = TestClient(app).post("/callback", json={})
    assert response.status_code == 200
    assert response.json() == {"error": 1}
    browser_auth.assert_not_awaited()


def test_neighbor_route_retains_browser_admission(monkeypatch):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    router = ScopedAPIRouter()

    @router.post("/editor")
    async def editor():
        pytest.fail("unauthenticated editor must not run")

    parent = ScopedAPIRouter()
    parent.include_router(router, request_scope=RequestScope.TENANT)
    app.include_router(parent)
    browser_auth = AsyncMock(side_effect=HTTPException(401, "Browser session absent"))
    monkeypatch.setattr(request_admission, "authenticate_browser", browser_auth)
    request_admission.install_request_admission(app)
    response = TestClient(app).post("/editor")
    assert response.status_code == 401
    browser_auth.assert_awaited_once()
