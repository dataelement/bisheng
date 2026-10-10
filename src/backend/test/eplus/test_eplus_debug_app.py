"""Standalone startup must not seed or mount the production application."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from bisheng.eplus.debug_app import create_app


def test_app_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EPLUS_DEBUG_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


def test_isolated_app_has_only_debug_routes_and_no_production_lifespan(monkeypatch):
    import bisheng.eplus.debug_app as module

    monkeypatch.setenv("EPLUS_DEBUG_ENABLED", "true")
    app = create_app()
    paths = {r.path for r in app.routes}
    assert "/robot-debug/api/status" in paths
    assert not any(p.startswith("/api/v1") or p.startswith("/api/v2") for p in paths)
    initialize, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module, "initialize_app_context", initialize)
    monkeypatch.setattr(module, "close_app_context", close)
    monkeypatch.setattr(module, "register_permission_context", lambda: None)
    monkeypatch.setattr(module, "configure_debug_logging", lambda: None)
    with TestClient(app):
        pass
    initialize.assert_awaited_once()
    close.assert_awaited_once()


def test_body_limit_before_authentication(monkeypatch):
    monkeypatch.setenv("EPLUS_DEBUG_ENABLED", "true")
    response = TestClient(create_app()).post("/robot-debug/api/assistants/a/run", content=b"x" * (512 * 1024 + 1))
    assert response.status_code == 413


def test_debug_auth_uses_same_cookie_first_selection_as_middleware(monkeypatch):
    from starlette.requests import Request
    from starlette.responses import Response

    from bisheng.eplus.debug_app import DebugAuthJwt
    from bisheng.user.domain.services.auth import AuthJwt

    monkeypatch.setattr(AuthJwt, "decode_jwt_token", lambda self, token: {"selected": token})

    def identity(headers):
        req = Request({"type": "http", "headers": headers})
        return DebugAuthJwt(req=req, res=Response()).get_subject()

    assert identity([(b"authorization", b"Bearer bearer-token")]) == {"selected": "bearer-token"}
    assert identity([(b"authorization", b"Bearer bearer-token"), (b"cookie", b"access_token_cookie=cookie-token")]) == {
        "selected": "cookie-token"
    }
