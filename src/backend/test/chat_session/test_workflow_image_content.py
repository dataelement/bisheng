"""HTTP integration for stable workflow image addresses (no external middleware)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bisheng.chat_session.api.endpoints.workflow_files import router
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.dependencies.user_deps import UserPayload


def test_content_endpoint_is_registered_on_session_router():
    """AC-01: the stable URL is wired into the application's session API router."""
    from bisheng.chat_session.api.router import router as session_router

    assert any(route.path == "/chat/{chat_id}/files/{file_id}/content" for route in session_router.routes)


def test_stable_image_address_reauthorizes_and_does_not_cache_signed_redirect(monkeypatch):
    """AC-05, AC-07: a historical URL resolves a fresh signature on every request."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    user = SimpleNamespace(user_id=7, tenant_id=1)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    resolve = AsyncMock(side_effect=["/main/image?signature=first", "/main/image?signature=second"])
    monkeypatch.setattr(ChatSessionService, "resolve_attachment_url", resolve)
    with TestClient(app) as client:
        first = client.get("/api/v1/chat/c1/files/asset/content", follow_redirects=False)
        second = client.get("/api/v1/chat/c1/files/asset/content", follow_redirects=False)
    assert first.status_code == second.status_code == 307
    assert first.headers["location"].endswith("signature=first")
    assert second.headers["location"].endswith("signature=second")
    assert first.headers["cache-control"] == "no-store"
    assert resolve.await_count == 2
    resolve.assert_awaited_with("c1", "asset", user)


@pytest.mark.parametrize("status", [401, 404])
def test_image_does_not_redirect_when_access_is_denied(monkeypatch, status):
    """AC-07: failed access never exposes a signed location."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=99)
    monkeypatch.setattr(ChatSessionService, "resolve_attachment_url", AsyncMock(side_effect=HTTPException(status)))
    with TestClient(app) as client:
        response = client.get("/api/v1/chat/c1/files/asset/content", follow_redirects=False)
    assert response.status_code == status
    assert "location" not in response.headers
