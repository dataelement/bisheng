"""Phone refresh sessions rotate, expire and revoke without changing web login."""

import asyncio
import hashlib
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import (
    DshMobileLoggedInElsewhereError,
    DshMobileTenantUnavailableError,
    DshMobileTokenVersionError,
    DshMobileUserDisabledError,
    DshRefreshTokenReusedError,
    DshSessionExpiredError,
    DshSessionRevokedError,
)
from bisheng.core.config.dsh import DshSettings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.dsh.api.endpoints.mobile import router
from bisheng.dsh.domain.models.mobile_session import DshMobileRefreshToken, DshMobileSession
from bisheng.dsh.domain.repositories.mobile_session import MobileSessionRepository
from bisheng.dsh.domain.services.mobile_session import MobileAccount, MobileSessionService
from bisheng.utils.http_middleware import owns_dsh_credential


class MemoryCurrentSession:
    def __init__(self):
        self.values = {}

    async def get(self, user_id):
        return self.values.get(user_id)

    async def put(self, user_id, token, ttl):
        self.values[user_id] = token


@pytest.fixture
def mobile(tmp_path):
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    register_tenant_filter_events()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'mobile-session.db'}",
        connect_args={"check_same_thread": False},
    )
    DshMobileSession.__table__.create(engine)
    DshMobileRefreshToken.__table__.create(engine)
    lock = threading.Lock()

    @contextmanager
    def scope():
        # SQLite ignores FOR UPDATE. This lock stands in for that row lock.
        with lock, Session(engine) as session, session.begin():
            yield MobileSessionRepository(session)

    accounts = {
        7: MobileAccount(user_id=7, tenant_id=3, user_name="alice", token_version=1),
    }
    issued = []
    flags = {"multi": False}
    clock = {"now": datetime(2026, 1, 1, 8, 0, 0)}
    current = MemoryCurrentSession()

    async def load_account(user_id, tenant_id, user_name):
        account = accounts.get(int(user_id))
        if account is None:
            return MobileAccount(user_id=int(user_id), tenant_id=int(tenant_id), user_active=False)
        return account

    def issue(account):
        token = f"access-{account.user_id}-{len(issued)}-{account.token_version}"
        issued.append(token)
        return token

    async def allow_multi():
        return flags["multi"]

    service = MobileSessionService(
        scope,
        session_seconds=2592000,
        access_seconds=86400,
        now=lambda: clock["now"],
        load_account=load_account,
        issue_access_token=issue,
        allow_multi_login=allow_multi,
        current_session=current,
    )
    return SimpleNamespace(
        engine=engine,
        service=service,
        accounts=accounts,
        current=current,
        clock=clock,
        flags=flags,
        issued=issued,
    )


def _session_row(engine, session_id=None):
    with bypass_tenant_filter(), Session(engine) as session:
        statement = select(DshMobileSession)
        if session_id is not None:
            statement = statement.where(DshMobileSession.session_id == session_id)
        return session.exec(statement).one()


def _token_states(engine):
    with bypass_tenant_filter(), Session(engine) as session:
        rows = session.exec(select(DshMobileRefreshToken).order_by(DshMobileRefreshToken.generation)).all()
        return [(row.generation, row.state) for row in rows]


def test_mobile_session_ttl_matches_the_desktop_session_default():
    settings = DshSettings()
    assert settings.mobile_session_ttl_seconds == settings.session_ttl_seconds == 2592000


def test_refresh_and_logout_routes_own_their_credential():
    assert owns_dsh_credential("POST", "/api/v1/dsh/mobile/session/refresh")
    assert owns_dsh_credential("DELETE", "/api/v1/dsh/mobile/session")
    assert not owns_dsh_credential("POST", "/api/v1/dsh/mobile/session")


async def test_open_stores_only_the_refresh_hash_and_current_access_token(mobile):
    opened = await mobile.service.open(7, 3, "alice")
    row = _session_row(mobile.engine)
    assert opened["refresh_token"] not in str(row)
    assert row.last_access_token_hash == hashlib.sha256(opened["access_token"].encode()).hexdigest()
    assert row.expires_at - row.created_at == timedelta(seconds=2592000)
    assert mobile.current.values[7] == opened["access_token"]
    assert _token_states(mobile.engine) == [(1, "ACTIVE")]


async def test_refresh_rotates_without_extending_the_absolute_expiry(mobile):
    opened = await mobile.service.open(7, 3, "alice")
    original_expiry = _session_row(mobile.engine).expires_at
    mobile.clock["now"] += timedelta(days=10)
    refreshed = await mobile.service.refresh(opened["refresh_token"])
    row = _session_row(mobile.engine)
    assert refreshed["refresh_token"] != opened["refresh_token"]
    assert refreshed["access_token"] != opened["access_token"]
    assert row.expires_at == original_expiry
    assert row.last_access_token_hash == hashlib.sha256(refreshed["access_token"].encode()).hexdigest()
    assert mobile.current.values[7] == refreshed["access_token"]
    assert _token_states(mobile.engine) == [(1, "USED"), (2, "ACTIVE")]
    again = await mobile.service.refresh(refreshed["refresh_token"])
    assert _session_row(mobile.engine).expires_at == original_expiry
    assert again["refresh_token"] != refreshed["refresh_token"]


async def test_replaying_a_used_refresh_token_revokes_the_session(mobile):
    opened = await mobile.service.open(7, 3, "alice")
    refreshed = await mobile.service.refresh(opened["refresh_token"])
    with pytest.raises(DshRefreshTokenReusedError):
        await mobile.service.refresh(opened["refresh_token"])
    assert _session_row(mobile.engine).state == "REVOKED"
    with pytest.raises(DshSessionRevokedError):
        await mobile.service.refresh(refreshed["refresh_token"])


def test_concurrent_refresh_has_one_winner_and_replay_revokes(mobile):
    opened = asyncio.run(mobile.service.open(7, 3, "alice"))
    outcomes = []

    def refresh_once():
        try:
            asyncio.run(mobile.service.refresh(opened["refresh_token"]))
            outcomes.append("ok")
        except DshRefreshTokenReusedError:
            outcomes.append("reused")

    threads = [threading.Thread(target=refresh_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ok", "reused"]
    assert _session_row(mobile.engine).state == "REVOKED"


async def test_absolute_expiry_rejects_refresh_without_moving_the_deadline(mobile):
    mobile.service.session_seconds = 30
    opened = await mobile.service.open(7, 3, "alice")
    original_expiry = _session_row(mobile.engine).expires_at
    mobile.clock["now"] += timedelta(seconds=31)
    with pytest.raises(DshSessionExpiredError):
        await mobile.service.refresh(opened["refresh_token"])
    row = _session_row(mobile.engine)
    assert row.expires_at == original_expiry
    assert row.state == "REVOKED"


async def test_logout_revokes_the_refresh_session(mobile):
    opened = await mobile.service.open(7, 3, "alice")
    await mobile.service.revoke(opened["refresh_token"])
    assert _session_row(mobile.engine).state == "REVOKED"
    with pytest.raises(DshSessionRevokedError):
        await mobile.service.refresh(opened["refresh_token"])
    await mobile.service.revoke("not-a-token")
    await mobile.service.revoke(opened["refresh_token"])


async def test_disabled_user_or_tenant_or_token_version_revokes(mobile):
    opened = await mobile.service.open(7, 3, "alice")
    mobile.accounts[7].user_active = False
    with pytest.raises(DshMobileUserDisabledError):
        await mobile.service.refresh(opened["refresh_token"])
    assert _session_row(mobile.engine).state == "REVOKED"

    mobile.accounts[7].user_active = True
    second = await mobile.service.open(7, 3, "alice")
    mobile.accounts[7].tenant_active = False
    with pytest.raises(DshMobileTenantUnavailableError):
        await mobile.service.refresh(second["refresh_token"])

    mobile.accounts[7].tenant_active = True
    third = await mobile.service.open(7, 3, "alice")
    mobile.accounts[7].token_version = 9
    with pytest.raises(DshMobileTokenVersionError):
        await mobile.service.refresh(third["refresh_token"])
    assert _session_row(mobile.engine, third["session_id"]).state == "REVOKED"


async def test_single_login_cannot_be_taken_back_and_multi_login_can_refresh(mobile):
    opened = await mobile.service.open(7, 3, "alice")
    mobile.current.values[7] = "someone-else"
    with pytest.raises(DshMobileLoggedInElsewhereError):
        await mobile.service.refresh(opened["refresh_token"])
    assert _token_states(mobile.engine) == [(1, "ACTIVE")]
    assert mobile.current.values[7] == "someone-else"

    mobile.current.values[7] = opened["access_token"]
    refreshed = await mobile.service.refresh(opened["refresh_token"])
    assert refreshed["access_token"] != opened["access_token"]

    mobile.flags["multi"] = True
    mobile.current.values[7] = "another-device"
    followed = await mobile.service.refresh(refreshed["refresh_token"])
    assert mobile.current.values[7] == followed["access_token"]


def test_http_refresh_does_not_require_an_access_token(mobile):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.mobile_sessions = mobile.service

    async def fake_user():
        return SimpleNamespace(user_id=7, tenant_id=3, user_name="alice")

    app.dependency_overrides[UserPayload.get_login_user] = fake_user
    client = TestClient(app)
    created = client.post("/api/v1/dsh/mobile/session")
    assert created.status_code == 200
    refresh_token = created.json()["data"]["refresh_token"]
    assert created.json()["data"]["access_token"]
    refreshed = client.post(
        "/api/v1/dsh/mobile/session/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["refresh_token"] != refresh_token
    deleted = client.request(
        "DELETE",
        "/api/v1/dsh/mobile/session",
        json={"refresh_token": refreshed.json()["data"]["refresh_token"]},
    )
    assert deleted.status_code == 204
    rejected = client.post(
        "/api/v1/dsh/mobile/session/refresh",
        json={"refresh_token": refreshed.json()["data"]["refresh_token"]},
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"] == "session_revoked"
