"""Real profile route + domain/repository, isolated authenticated subject."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from bisheng.user.domain.models.user import User
from bisheng.user.domain.services.nickname_service import NicknameService
from test.user.f011_fixtures import identity_store, nickname_store, old_user  # noqa: F401


@pytest.fixture
def profile_api(nickname_store, monkeypatch, tmp_path):  # noqa: F811
    # Import-only settings never point at a company database or middleware.
    settings_file = tmp_path / "nickname-settings.yaml"
    settings_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("config", settings_file.as_posix())
    from bisheng.user.api.endpoints import profile

    engine, _ = nickname_store
    actor = old_user(engine, account="self")
    other = old_user(engine, account="other")
    monkeypatch.setattr(NicknameService, "profile_enabled", staticmethod(lambda: False))
    app = FastAPI()
    app.include_router(profile.router, prefix="/api/v1")

    async def current_actor():
        return SimpleNamespace(user_id=actor.user_id, user_name=actor.user_name, tenant_id=1)

    app.dependency_overrides[profile.UserPayload.get_login_user] = current_actor
    with TestClient(app) as client:
        yield client, app, profile, engine, actor, other


def test_current_user_is_derived_and_response_omits_private_fields(profile_api):
    """AC-18, AC-22: no public target parameter, account and other identity stay intact."""
    client, _, _, engine, actor, other = profile_api
    response = client.patch("/api/v1/user/profile/nickname", json={"user_name": "新昵称"})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"status_code", "status_message", "data"}
    assert payload["status_code"] == 200
    assert payload["data"] == {"user_id": actor.user_id, "user_name": "新昵称", "external_id": actor.external_id}
    with Session(engine) as session:
        assert session.get(User, other.user_id).user_name == other.user_name
        assert session.get(User, actor.user_id).user_name == "新昵称"


@pytest.mark.parametrize(
    "extra", [{"user_id": 999}, {"external_id": "replacement"}, {"role_ids": [1]}, {"nickname_customized": False}]
)
def test_extra_identity_and_permission_fields_are_rejected(profile_api, extra):
    """AC-18: mass assignment cannot choose target or change protected data."""
    client, _, _, engine, actor, _ = profile_api
    response = client.patch("/api/v1/user/profile/nickname", json={"user_name": "新昵称", **extra})
    assert response.status_code == 422
    with Session(engine) as session:
        assert session.get(User, actor.user_id).user_name == actor.user_name


def test_domain_error_is_wrapped(profile_api):
    """AC-31: stable nickname error code for invalid direct requests."""
    client, *_ = profile_api
    response = client.patch("/api/v1/user/profile/nickname", json={"user_name": "bad name"})
    assert response.json()["status_code"] == 10614


def test_unauthenticated_user_cannot_change_nickname(profile_api):
    """AC-18: paired deny path before domain persistence."""
    client, app, profile, engine, actor, _ = profile_api

    async def no_actor():
        raise HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[profile.UserPayload.get_login_user] = no_actor
    assert client.patch("/api/v1/user/profile/nickname", json={"user_name": "新昵称"}).status_code == 401
    with Session(engine) as session:
        assert session.get(User, actor.user_id).user_name == actor.user_name
