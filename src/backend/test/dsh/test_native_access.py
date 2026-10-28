"""Native DSH flow with real SQL and cryptography. 覆盖 AC: AC-01, AC-02, AC-03, AC-09, AC-11."""

import asyncio
import base64
import hashlib
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import (
    DshInvalidAccessTokenError,
    DshRefreshTokenReusedError,
    DshSessionRevokedError,
    DshUserDisabledError,
)
from bisheng.dsh.access_runtime import DshRuntime, get_logout_runtime, get_runtime
from bisheng.dsh.api.endpoints.local_auth import router
from bisheng.dsh.domain.models.local_session import DshRefreshToken, DshSession
from bisheng.dsh.domain.repositories.local_session import DshSessionRepository
from bisheng.dsh.domain.repositories.tickets import TicketRepository
from bisheng.dsh.domain.schemas.contracts import DshIdentitySnapshot, DshTenantDisplay, DshUserDisplay
from bisheng.dsh.domain.services.access import DshAccessService, DshPrincipal, principal_scope
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.dsh.domain.services.identity import IdentityService
from bisheng.dsh.domain.services.local_session import DshLocalSessionService
from bisheng.dsh.infrastructure.token_keys import ISSUER, LocalTokenKeys


class RedisStore:
    """Deterministic external Redis boundary; SQL and token logic remain real."""

    def __init__(self):
        self.data = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.data:
            return False
        self.data[key] = (value, time.monotonic() + ex)
        return True

    async def eval(self, script, count, key, *args):
        if "INCR" in script:
            return 1
        stored = self.data.get(key)
        if stored is None or stored[1] <= time.monotonic():
            return []
        if "decoded.binding" in script:
            if json.loads(stored[0])["binding"] != args[0]:
                return None
            del self.data[key]
            return stored[0]
        return [stored[0], int(stored[1] - time.monotonic())]


def snapshot(user="20", tenant="2", active=True):
    if not active:
        return DshIdentitySnapshot(user_id=user, tenant_id=tenant, active=False, reason="user_disabled")
    return DshIdentitySnapshot(
        user_id=user,
        tenant_id=tenant,
        active=True,
        profile_version=1,
        user=DshUserDisplay(id=user, username="alice", display_name="Alice"),
        tenant=DshTenantDisplay(id=tenant, name="Tenant"),
    )


@pytest.fixture
def native(tmp_path):
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    register_tenant_filter_events()
    engine = create_engine(f"sqlite:///{tmp_path / 'native.db'}", connect_args={"check_same_thread": False})
    DshSession.__table__.create(engine)
    DshRefreshToken.__table__.create(engine)

    @contextmanager
    def scope():
        with Session(engine) as session, session.begin():
            yield DshSessionRepository(session)

    records = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                active=True,
                natural_person=True,
                username="alice",
                tenant_active=True,
                tenant_id="2",
                user_id="20",
                display_name="Alice",
                tenant_name="Tenant",
                profile_version=1,
            )
        )
    )
    store = RedisStore()
    authorizations = DshAuthorizationService(store, "https://platform.example")
    identity = IdentityService(TicketRepository(store), records, authorizations)
    keys = LocalTokenKeys(lambda: "synthetic-persistent-master-for-native-tests")
    sessions = DshLocalSessionService(scope, identity, keys, refresh_grace_seconds=600)
    access = DshAccessService(ISSUER, keys, identity, sessions)
    runtime = DshRuntime(
        SimpleNamespace(platform_public_url="https://platform.example"), identity, access, sessions, authorizations
    )
    yield runtime, engine
    engine.dispose()


async def login(runtime):
    return await runtime.sessions.exchange(snapshot(), "00000000-0000-4000-8000-" + str(time.time_ns())[-12:], {})


async def test_native_tokens_validate_and_replay_revokes_the_family(native):
    runtime, engine = native
    result = await login(runtime)
    claims = jwt.decode(result["access_token"], options={"verify_signature": False})
    assert "seat_id" not in claims and "grant_version" not in claims
    principal = await runtime.access.authenticate("Bearer " + result["access_token"])
    assert principal.user_id == "20" and principal.tenant_id == "2"
    with principal_scope(principal):
        rotated = await runtime.sessions.refresh(result["refresh_token"])
    assert rotated["session_id"] == result["session_id"]
    assert rotated["refresh_token"] != result["refresh_token"]
    # The successor has never been presented, so retrying the old token is a lost response.
    recovered = await runtime.sessions.refresh(result["refresh_token"])
    assert recovered["session_id"] == result["session_id"]
    await runtime.access.authenticate("Bearer " + rotated["access_token"])
    await runtime.sessions.refresh(recovered["refresh_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(result["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + rotated["access_token"])
    with Session(engine) as session, principal_scope(DshPrincipal(tenant_id="2", user_id="20", session_id="test")):
        # SQL assertion proves revocation committed before the replay error.
        assert all(row.state == "REVOKED" for row in session.exec(select(DshSession)).all())
        assert all(row.state == "REVOKED" for row in session.exec(select(DshRefreshToken)).all())


def rewrite_used_at(engine, used_at):
    with Session(engine) as session, principal_scope(DshPrincipal(tenant_id="2", user_id="20", session_id="test")):
        row = session.exec(select(DshRefreshToken).where(DshRefreshToken.state == "USED")).one()
        row.used_at = used_at
        session.add(row)
        session.commit()


async def test_replaced_successor_revokes_after_grace_reissue(native):
    runtime, _ = native
    issued = await login(runtime)
    lost = await runtime.sessions.refresh(issued["refresh_token"])
    recovered = await runtime.sessions.refresh(issued["refresh_token"])
    await runtime.access.authenticate("Bearer " + recovered["access_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(lost["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + recovered["access_token"])


async def test_repeated_lost_refresh_keeps_only_the_latest_successor(native):
    runtime, _ = native
    issued = await login(runtime)
    await runtime.sessions.refresh(issued["refresh_token"])
    replaced = await runtime.sessions.refresh(issued["refresh_token"])
    latest = await runtime.sessions.refresh(issued["refresh_token"])
    continued = await runtime.sessions.refresh(latest["refresh_token"])
    await runtime.access.authenticate("Bearer " + continued["access_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(replaced["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + continued["access_token"])


async def test_refresh_replay_outside_grace_revokes_the_session(native):
    runtime, engine = native
    issued = await login(runtime)
    rotated = await runtime.sessions.refresh(issued["refresh_token"])
    rewrite_used_at(engine, datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=601))
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(issued["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + rotated["access_token"])


async def test_historical_used_token_without_timestamp_revokes(native):
    runtime, engine = native
    issued = await login(runtime)
    rotated = await runtime.sessions.refresh(issued["refresh_token"])
    rewrite_used_at(engine, None)
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(issued["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + rotated["access_token"])


async def test_zero_grace_keeps_strict_replay(native):
    runtime, engine = native
    runtime.sessions.refresh_grace_seconds = 0
    issued = await login(runtime)
    await runtime.sessions.refresh(issued["refresh_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(issued["refresh_token"])
    with Session(engine) as session, principal_scope(DshPrincipal(tenant_id="2", user_id="20", session_id="test")):
        assert all(row.state == "REVOKED" for row in session.exec(select(DshSession)).all())


async def test_grace_on_one_device_leaves_the_other_session_active(native):
    runtime, _ = native
    first, second = await login(runtime), await login(runtime)
    lost = await runtime.sessions.refresh(first["refresh_token"])
    await runtime.sessions.refresh(first["refresh_token"])
    await runtime.access.authenticate("Bearer " + second["access_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(lost["refresh_token"])
    await runtime.access.authenticate("Bearer " + second["access_token"])


async def test_grace_follows_behavior_after_a_long_rotation_chain(native):
    runtime, _ = native
    current = await login(runtime)
    history = [current["refresh_token"]]
    for _ in range(30):
        current = await runtime.sessions.refresh(current["refresh_token"])
        history.append(current["refresh_token"])
    recovered = await runtime.sessions.refresh(history[-2])
    continued = await runtime.sessions.refresh(recovered["refresh_token"])
    await runtime.access.authenticate("Bearer " + continued["access_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await runtime.sessions.refresh(history[-4])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + continued["access_token"])


async def test_logout_is_idempotent_and_does_not_revoke_other_devices(native):
    runtime, _ = native
    first, second = await login(runtime), await login(runtime)
    await runtime.sessions.logout_refresh(first["refresh_token"])
    await runtime.sessions.logout_refresh(first["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.access.authenticate("Bearer " + first["access_token"])
    await runtime.access.authenticate("Bearer " + second["access_token"])
    page = await runtime.sessions.page(2, 20)
    assert len(page["items"]) == 2
    assert not any("seat_id" in row for row in page["items"])


async def test_disabled_identity_and_cross_tenant_ownership(native):
    runtime, _ = native
    result = await login(runtime)
    with pytest.raises(DshInvalidAccessTokenError):
        await runtime.sessions.revoke(3, 20, result["session_id"])
    runtime.identity.identities.get.return_value.active = False
    from bisheng.common.errcode.dsh import DshUserDisabledError

    with pytest.raises(DshUserDisabledError):
        await runtime.access.authenticate("Bearer " + result["access_token"])


@pytest.mark.parametrize("path", ["/api/dsh", "/api/v1/dsh"])
def test_pkce_browser_ticket_exchange_and_refresh_end_to_end(native, path):
    runtime, _ = native
    from bisheng.dsh.api.endpoints.identity import browser_user
    from bisheng.dsh.api.endpoints.identity import router as browser_router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(router, prefix="/api")
    app.include_router(browser_router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_logout_runtime] = lambda: runtime
    app.dependency_overrides[browser_user] = lambda: SimpleNamespace(tenant_id=2, user_id=20)
    verifier = "v" * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with TestClient(app) as client:
        auth = client.post(
            path + "/authorizations",
            json={
                "client_id": "dsh-desktop",
                "redirect_uri": "http://127.0.0.1:43123/dsh/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s" * 32,
            },
        )
        assert auth.status_code == 200, auth.text
        auth_id = auth.json()["auth_id"]
        approved = client.post(
            "/api/v1/dsh/authorize", json={"auth_id": auth_id}, headers={"Origin": "https://platform.example"}
        )
        # The existing browser endpoint also verifies the platform origin.
        assert approved.status_code == 200, approved.text
        ticket = approved.json()["data"]["identity_ticket"]
        bad = client.post(
            path + "/token",
            json={
                "grant_type": "identity_ticket",
                "auth_id": auth_id,
                "identity_ticket": ticket,
                "code_verifier": "x" * 43,
            },
        )
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "pkce_verification_failed"
        token = client.post(
            path + "/token",
            json={
                "grant_type": "identity_ticket",
                "auth_id": auth_id,
                "identity_ticket": ticket,
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200, token.text
        again = client.post(
            path + "/token",
            json={
                "grant_type": "identity_ticket",
                "auth_id": auth_id,
                "identity_ticket": ticket,
                "code_verifier": verifier,
            },
        )
        assert again.status_code == 400
        refreshed = client.post(
            path + "/token", json={"grant_type": "refresh_token", "refresh_token": token.json()["refresh_token"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        held = refreshed.json()["refresh_token"]
        lost = client.post(path + "/token", json={"grant_type": "refresh_token", "refresh_token": held})
        assert lost.status_code == 200, lost.text
        recovered = client.post(path + "/token", json={"grant_type": "refresh_token", "refresh_token": held})
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["refresh_token"] != lost.json()["refresh_token"]
        principal = asyncio.run(runtime.access.authenticate("Bearer " + recovered.json()["access_token"]))
        assert principal.user_id == "20"
        assert (
            client.post(path + "/logout", json={"refresh_token": recovered.json()["refresh_token"]}).status_code == 204
        )


@pytest.mark.parametrize(
    "change", [{"aud": "web"}, {"tenant_id": "3"}, {"seat_id": "legacy"}, {"session_version": True}]
)
async def test_token_contract_rejects_wrong_purpose_identity_or_shape(native, change):
    runtime, _ = native
    token = (await login(runtime))["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(change)
    from bisheng.dsh.infrastructure.token_keys import KEY_ID

    token = jwt.encode(
        claims,
        await runtime.access.keys.resolve(KEY_ID),
        algorithm="HS256",
        headers={"kid": KEY_ID, "typ": "bisheng-dsh-access+jwt"},
    )
    with pytest.raises(DshUserDisabledError if "tenant_id" in change else DshInvalidAccessTokenError):
        await runtime.access.authenticate("Bearer " + token)


async def test_session_pages_remain_exactly_tenant_scoped_even_when_root_is_visible(native):
    runtime, _engine = native
    first = await login(runtime)
    root_identity = DshIdentitySnapshot(
        tenant_id="1",
        user_id="20",
        active=True,
        user=DshUserDisplay(id="20", username="root", display_name="Root"),
        tenant=DshTenantDisplay(id="1", name="Root"),
        profile_version=1,
    )
    root_login = await runtime.sessions.exchange(root_identity, "foreign-auth", {})
    page = await runtime.sessions.page(2, 20)
    assert [row["session_id"] for row in page["items"]] == [first["session_id"]]
    with pytest.raises(DshInvalidAccessTokenError):
        await runtime.sessions.revoke(2, 20, root_login["session_id"])
    assert (await runtime.sessions.page(1, 20))["items"][0]["state"] == "ACTIVE"


async def test_native_token_response_is_accepted_by_desktop_parser(native):
    import os
    import subprocess
    from pathlib import Path

    desktop = os.environ.get("DSH_DESKTOP_SOURCE_DIR")
    if not desktop:
        pytest.skip(
            "Set DSH_DESKTOP_SOURCE_DIR to the isolated desktop checkout for cross-repository contract verification"
        )
    contract = (Path(desktop) / "packages/dsh-desktop-enterprise/contract.js").resolve()
    assert contract.is_file()
    runtime, _engine = native
    response = await login(runtime)
    script = """
import { readFileSync } from 'node:fs';
const { parseToken } = await import(process.argv[1]);
const parsed = parseToken(JSON.parse(readFileSync(0, 'utf8')), 'https://platform.example');
if (parsed.user.id !== '20' || parsed.tenant.id !== '2' || !parsed.session_id) process.exit(1);
process.stdout.write('native-contract-ok');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, contract.as_uri()],
        input=json.dumps(response),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, "Desktop parser rejected the native token contract"
    assert result.stdout == "native-contract-ok"
