"""The deprecated unsigned SSO endpoint must never issue credentials."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("pro_enabled", [False, True])
@pytest.mark.parametrize("payload", [{"user_name": "admin"}, {"user_name": "new-user"}, {}])
def test_legacy_sso_is_gone_before_identity_lookup(monkeypatch, pro_enabled, payload):
    from bisheng.user.api import user as endpoints

    settings = MagicMock()
    settings.get_system_login_method.return_value = SimpleNamespace(bisheng_pro=pro_enabled)
    monkeypatch.setattr(endpoints, "settings", settings)
    lookup = MagicMock(side_effect=AssertionError("Unsigned SSO must not query users"))
    monkeypatch.setattr(endpoints.UserDao, "get_unique_user_by_name", lookup)
    issue = MagicMock(side_effect=AssertionError("Unsigned SSO must not issue tokens"))
    monkeypatch.setattr(endpoints.LoginUser, "create_access_token", issue)
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    # The old handler used to construct AuthJwt before any business guard.
    app.dependency_overrides[endpoints.AuthJwt] = lambda: SimpleNamespace()
    response = TestClient(app).post("/api/v1/user/sso", json=payload)
    assert response.status_code == 410
    assert "login-sync" in response.json()["detail"]
    assert "access_token" not in response.text
    lookup.assert_not_called()
    issue.assert_not_called()
