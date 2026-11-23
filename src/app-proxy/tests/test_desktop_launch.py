"""Desktop launch uses an app-bound cookie, never a platform session."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.requests import Request
from starlette.testclient import TestClient

from app_proxy import desktop
from app_proxy.authz import extract_access_token
from app_proxy.headers import strip_platform_headers
from app_proxy.main import create_app


def test_launch_posts_ticket_and_sets_scoped_cookie(monkeypatch):
    peer = SimpleNamespace(redeem_desktop=AsyncMock(return_value={"session": "bs-view-" + "s" * 43}))
    monkeypatch.setattr(desktop, "get_backend_client", lambda: peer)
    monkeypatch.setattr(desktop, "get_config", lambda: SimpleNamespace(entry_prefix="/apps", entry_base_url="https://example.test"))
    with TestClient(create_app(), base_url="https://example.test") as client:
        response = client.post("/apps/demo/_desktop", data={"ticket": "t" * 43}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/apps/demo/"
    cookie = response.headers["set-cookie"]
    assert "bisheng_app_session_demo=bs-view-" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "Path=/apps/demo/" in cookie
    assert "access_token_cookie" not in cookie
    peer.redeem_desktop.assert_awaited_once_with(slug="demo", ticket="t" * 43)


def test_bad_ticket_is_rejected_before_backend(monkeypatch):
    peer = SimpleNamespace(redeem_desktop=AsyncMock())
    monkeypatch.setattr(desktop, "get_backend_client", lambda: peer)
    with TestClient(create_app()) as client:
        for data in ({"ticket": "bad"}, {"ticket": "t" * 43, "extra": "x"}):
            assert client.post("/apps/demo/_desktop", data=data).status_code == 400
    peer.redeem_desktop.assert_not_called()


def test_native_exchange_sets_same_scoped_cookie_without_redirect(monkeypatch):
    peer = SimpleNamespace(redeem_desktop=AsyncMock(return_value={"session": "bs-view-" + "s" * 43}))
    monkeypatch.setattr(desktop, "get_backend_client", lambda: peer)
    monkeypatch.setattr(desktop, "get_config", lambda: SimpleNamespace(entry_prefix="/apps", entry_base_url="https://example.test"))
    with TestClient(create_app(), base_url="https://example.test") as client:
        response = client.post("/apps/demo/_desktop", data={"ticket": "t" * 43},
                               headers={"Accept": "application/json"}, follow_redirects=False)
    assert response.status_code == 204
    assert "location" not in response.headers
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Accept"
    cookie = response.headers["set-cookie"]
    assert "bisheng_app_session_demo=bs-view-" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "Path=/apps/demo/" in cookie
    peer.redeem_desktop.assert_awaited_once_with(slug="demo", ticket="t" * 43)


def test_native_exchange_does_not_turn_expired_ticket_into_success(monkeypatch):
    from app_proxy.clients import InternalRpcError

    peer = SimpleNamespace(redeem_desktop=AsyncMock(side_effect=InternalRpcError("backend", "expired")))
    monkeypatch.setattr(desktop, "get_backend_client", lambda: peer)
    with TestClient(create_app()) as client:
        response = client.post("/apps/demo/_desktop", data={"ticket": "t" * 43}, headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_desktop_cookie_is_app_specific_and_never_reaches_container():
    headers = [("cookie", "access_token_cookie=platform; bisheng_app_session_demo=bs-view-abc; theme=dark")]
    request = Request({"type": "http", "path": "/apps/demo/", "path_params": {"slug": "demo"},
                       "headers": [(b"cookie", headers[0][1].encode())]})
    assert extract_access_token(request) == "bs-view-abc"
    assert strip_platform_headers(headers) == [("cookie", "theme=dark")]
    request.scope["path_params"]["slug"] = "different"
    assert extract_access_token(request) == "platform"
