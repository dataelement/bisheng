"""Desktop avatar reads are live, profile-only, and bound to the Bearer identity."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.errcode.dsh import DshSessionRevokedError, DshUserDisabledError
from bisheng.core.context import tenant as tenant_context
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints.models import router
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh.domain.services.identity import IdentityRecord, IdentityService
from test.dsh.test_access import Keys, token


@pytest.fixture
def profile_runtime():
    records = SimpleNamespace(
        get=AsyncMock(return_value=IdentityRecord("2", "1001", "alice", "Alice", "Enterprise", 7, True, True, True))
    )
    reader = AsyncMock(return_value="https://objects.example/avatar.png?signature=fresh")
    identity = IdentityService(None, records, None, avatar_reader=reader)
    sessions = SimpleNamespace(validate=AsyncMock(), record_activity=AsyncMock())
    runtime = SimpleNamespace(
        identity=identity,
        sessions=sessions,
        access=DshAccessService("test-issuer", Keys(), identity, sessions),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app, runtime, records, reader


async def test_bearer_profile_reads_live_avatar_without_renewing_activity(profile_runtime):
    app, runtime, records, reader = profile_runtime
    seen_scopes = []

    async def read_avatar(tenant_id, user_id):
        seen_scopes.append((tenant_context.get_current_tenant_id(), tenant_id, user_id))
        return reader.return_value

    reader.side_effect = read_avatar
    inherited = tenant_context.set_current_tenant_id(99)
    inherited_admin = tenant_context.set_admin_scope_tenant_id(99)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example"
        ) as client:
            for avatar in (None, "https://objects.example/new.png?signature=2", None):
                reader.return_value = avatar
                response = await client.get(
                    "/api/v1/dsh/profile?tenant_id=999&user_id=999", headers={"Authorization": "Bearer " + token()}
                )
                assert response.status_code == 200
                assert response.json() == {
                    "user": {"id": "1001", "username": "alice", "display_name": "Alice", "avatar": avatar},
                    "tenant": {"id": "2", "name": "Enterprise"},
                }
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["referrer-policy"] == "no-referrer"
                assert tenant_context.get_current_tenant_id() == 99
        assert seen_scopes == [(2, "2", "1001")] * 3
        assert records.get.await_count == 6  # Authentication + live profile validation, never a token snapshot.
        assert runtime.sessions.validate.await_count == 3
        runtime.sessions.record_activity.assert_not_awaited()  # Polling profile is not business activity.
    finally:
        inherited_admin.var.reset(inherited_admin)
        inherited.var.reset(inherited)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Cookie": "access_token_cookie=browser-session"},
        {"Authorization": "Bearer pat_not-a-desktop-token"},
        {"Authorization": "Basic wrong"},
        [("Authorization", "Bearer one"), ("Authorization", "Bearer two")],
    ],
)
async def test_profile_requires_one_desktop_bearer_before_reading_avatar(profile_runtime, headers):
    app, runtime, records, reader = profile_runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.get("/api/v1/dsh/profile", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"
    reader.assert_not_awaited()
    records.get.assert_not_awaited()
    runtime.sessions.validate.assert_not_awaited()
    runtime.sessions.record_activity.assert_not_awaited()


async def test_revoked_session_cannot_read_avatar(profile_runtime):
    app, runtime, _, reader = profile_runtime
    runtime.sessions.validate.side_effect = DshSessionRevokedError()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.get("/api/v1/dsh/profile", headers={"Authorization": "Bearer " + token()})
    assert response.status_code == 401
    reader.assert_not_awaited()
    runtime.sessions.record_activity.assert_not_awaited()


async def test_check_never_signs_even_with_a_broken_avatar_reader(profile_runtime):
    _, runtime, _, reader = profile_runtime
    reader.side_effect = RuntimeError("signer unavailable")
    snapshot = await runtime.identity.check("2", "1001")
    assert snapshot.active and snapshot.profile_version == 7
    assert "avatar" not in snapshot.user.model_dump()
    reader.assert_not_awaited()
    with pytest.raises(RuntimeError, match="signer unavailable"):
        await runtime.identity.profile("2", "1001")
    reader.assert_awaited_once_with("2", "1001")


@pytest.mark.parametrize(
    "changes",
    [
        {"active": False},
        {"natural_person": False},
        {"tenant_active": False},
        {"tenant_id": "3"},
        {"user_id": "1002"},
        {"username": " "},
    ],
)
async def test_profile_rechecks_identity_before_signing(profile_runtime, changes):
    _, runtime, records, reader = profile_runtime
    records.get.return_value = replace(records.get.return_value, **changes)
    with pytest.raises(DshUserDisabledError):
        await runtime.identity.profile("2", "1001")
    reader.assert_not_awaited()


async def test_profile_without_injected_reader_has_explicit_null_avatar(profile_runtime):
    _, _, records, reader = profile_runtime
    identity = IdentityService(None, records, None)
    assert (await identity.profile("2", "1001"))["user"]["avatar"] is None
    reader.assert_not_awaited()


async def test_build_runtime_injects_avatar_reader_into_shared_identity(monkeypatch):
    from bisheng.core.cache import redis_manager
    from bisheng.dsh import access_runtime
    from bisheng.dsh.config import DshSettings
    from bisheng.user.domain.services import dsh_avatar

    redis = object()
    redis_factory = AsyncMock(return_value=SimpleNamespace(async_connection=redis))
    reader = AsyncMock(return_value="signed-avatar")
    monkeypatch.setattr(redis_manager, "get_redis_client", redis_factory)
    monkeypatch.setattr(dsh_avatar, "read_dsh_avatar", reader)
    runtime = await access_runtime.build_runtime(DshSettings())
    assert runtime.identity.avatar_reader is reader
    assert runtime.access.identities is runtime.identity
    assert runtime.sessions.identities is runtime.identity
    redis_factory.assert_awaited_once_with()
    reader.assert_not_awaited()  # Composition itself must not touch object storage.
    monkeypatch.setattr(
        runtime.identity.identities,
        "get",
        AsyncMock(return_value=IdentityRecord("2", "1001", "alice", None, None, 0, True, True, True)),
    )
    assert (await runtime.identity.profile("2", "1001"))["user"]["avatar"] == "signed-avatar"
    reader.assert_awaited_once_with("2", "1001")
