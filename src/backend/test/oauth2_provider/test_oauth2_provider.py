"""End-to-end and unit tests for the OAuth 2.0 / OIDC Provider and DSH client integration."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshDshDisabledError, DshInvalidRequestError
from bisheng.common.errcode.oauth2_provider import (
    OAuth2BuiltinClientProtectedError,
    OAuth2ClientAlreadyExistsError,
    OAuth2InvalidClientAuthError,
    OAuth2InvalidGrantError,
    OAuth2InvalidRedirectUriError,
    OAuth2PkceVerificationFailedError,
)
from bisheng.dsh.api.endpoints.local_auth import AuthorizationRequest
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.oauth2_provider.api.endpoints.clients import admin_router, require_super_admin
from bisheng.oauth2_provider.api.endpoints.oidc import consent_router, public_router
from bisheng.oauth2_provider.api.router import well_known_router
from bisheng.oauth2_provider.domain.models.client import BUILTIN_DSH_CLIENT_ID, OAuth2Client
from bisheng.oauth2_provider.domain.models.session import OAuth2RefreshToken, OAuth2Session
from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientCreate, OAuth2ClientUpdate
from bisheng.oauth2_provider.domain.services.auth_service import OAuth2AuthService, OAuth2UserIdentity
from bisheng.oauth2_provider.domain.services.client_service import (
    OAuth2ClientService,
    match_redirect_uri,
)
from bisheng.oauth2_provider.infrastructure.code_store import OAuth2CodeStore
from bisheng.oauth2_provider.infrastructure.key_service import OAuth2KeyService
from bisheng.oauth2_provider.runtime import OAuth2ProviderRuntime, get_oauth2_runtime


class FakeRedis:
    def __init__(self):
        self._data: dict[str, tuple[str, int]] = {}
        self._counters: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int = 300, nx: bool = False):
        if nx and key in self._data:
            return False
        self._data[key] = (value, ex)
        return True

    async def get(self, key: str):
        item = self._data.get(key)
        return item[0] if item else None

    async def ttl(self, key: str):
        item = self._data.get(key)
        return item[1] if item else -2

    async def getdel(self, key: str):
        item = self._data.pop(key, None)
        return item[0] if item else None

    async def incr(self, key: str):
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def expire(self, key: str, ttl: int):
        return True

    async def eval(self, script: str, numkeys: int, key: str):
        item = self._data.get(key)
        if not item:
            return []
        return [item[0], item[1]]


def _make_pkce(verifier: str = "a" * 64) -> tuple[str, str]:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


@pytest.fixture
def oauth2_env(tmp_path):
    # Separate connections exercise committed CAS state, unlike StaticPool.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'oauth2.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[OAuth2Client.__table__, OAuth2Session.__table__, OAuth2RefreshToken.__table__],
    )

    @contextmanager
    def session_factory():
        with Session(engine) as db:
            yield db
            db.commit()

    redis = FakeRedis()
    keys = OAuth2KeyService(secret_reader=lambda: "unit-test-master-secret-for-oauth2-provider")
    clients = OAuth2ClientService(session_factory)
    code_store = OAuth2CodeStore(redis)

    async def fake_identity(tenant_id: int, user_id: int) -> OAuth2UserIdentity | None:
        if user_id == 999:
            return OAuth2UserIdentity(
                user_id=999,
                tenant_id=tenant_id,
                username="disabled",
                display_name="Disabled",
                email="disabled@example.com",
                tenant_name="Root",
                active=False,
            )
        return OAuth2UserIdentity(
            user_id=user_id,
            tenant_id=tenant_id,
            username="alice",
            display_name="Alice Wang",
            email="alice@example.com",
            tenant_name="Acme Corp",
            active=True,
        )

    auth = OAuth2AuthService(
        clients=clients,
        code_store=code_store,
        keys=keys,
        session_factory=session_factory,
        identity_lookup=fake_identity,
    )
    runtime = OAuth2ProviderRuntime(clients=clients, auth=auth, keys=keys)
    return runtime, redis


def test_redirect_uri_matching_loopback_and_exact():
    assert match_redirect_uri(
        "http://127.0.0.1:54321/dsh/callback",
        ["http://127.0.0.1/dsh/callback"],
        allow_loopback_port=True,
    )
    assert not match_redirect_uri(
        "http://127.0.0.1:54321/dsh/callback",
        ["http://127.0.0.1/dsh/callback"],
        allow_loopback_port=False,
    )
    assert not match_redirect_uri(
        "http://evil.example.com:54321/dsh/callback",
        ["http://127.0.0.1/dsh/callback"],
        allow_loopback_port=True,
    )
    assert match_redirect_uri(
        "https://app.example.com/oauth/callback",
        ["https://app.example.com/oauth/callback"],
        allow_loopback_port=False,
    )


async def test_client_crud_and_builtin_protection(oauth2_env):
    runtime, _ = oauth2_env
    rows, total = await runtime.clients.list_clients()
    assert total == 1
    assert rows[0].client_id == BUILTIN_DSH_CLIENT_ID
    assert rows[0].is_builtin is True

    with pytest.raises(OAuth2BuiltinClientProtectedError):
        await runtime.clients.delete_client(BUILTIN_DSH_CLIENT_ID)

    created = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="partner-web",
            client_name="Partner Web",
            client_type="confidential",
            redirect_uris=["https://partner.example.com/cb"],
            require_pkce=True,
            require_consent=True,
        )
    )
    assert created.client.client_id == "partner-web"
    assert created.client_secret and created.client_secret.startswith("bss_")
    assert created.client.has_secret is True

    with pytest.raises(OAuth2ClientAlreadyExistsError):
        await runtime.clients.create_client(
            OAuth2ClientCreate(
                client_id="partner-web",
                client_name="Duplicate",
                redirect_uris=["https://partner.example.com/cb"],
            )
        )

    rotated = await runtime.clients.rotate_secret("partner-web")
    assert rotated.client_secret != created.client_secret

    updated = await runtime.clients.update_client("partner-web", OAuth2ClientUpdate(require_consent=False))
    assert updated.require_consent is False

    await runtime.clients.delete_client("partner-web")
    rows_after, total_after = await runtime.clients.list_clients()
    assert total_after == 1
    assert [r.client_id for r in rows_after] == [BUILTIN_DSH_CLIENT_ID]


async def test_full_oidc_authorization_code_refresh_userinfo_revoke(oauth2_env):
    runtime, _ = oauth2_env
    created = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="web-app",
            client_name="Web App",
            client_type="confidential",
            redirect_uris=["https://web.example.com/callback"],
            allowed_scopes=["openid", "profile", "email", "offline_access"],
            require_pkce=True,
            require_consent=True,
        )
    )
    verifier, challenge = _make_pkce("v" * 64)
    request_id, _, _ = await runtime.auth.start_authorization(
        client_id="web-app",
        redirect_uri="https://web.example.com/callback",
        response_type="code",
        scope="openid profile email offline_access",
        state="state-1234567890",
        code_challenge=challenge,
        code_challenge_method="S256",
        nonce="nonce-xyz",
    )

    details = await runtime.auth.get_consent_details(request_id)
    assert details.client_name == "Web App"
    assert details.scopes == ["openid", "profile", "email", "offline_access"]

    consent = await runtime.auth.submit_consent(
        request_id=request_id,
        user_id=42,
        tenant_id=7,
        decision="approve",
    )
    parsed = urlsplit(consent.redirect_uri)
    q = parse_qs(parsed.query)
    assert q["state"] == ["state-1234567890"]
    code = q["code"][0]

    # Wrong PKCE fails (and code is single-use, so test wrong secret before consuming code)
    with pytest.raises(OAuth2InvalidClientAuthError):
        await runtime.auth.exchange_code(
            origin="https://bisheng.example.com",
            code=code,
            client_id="web-app",
            redirect_uri="https://web.example.com/callback",
            code_verifier=verifier,
            client_secret="wrong-secret",
        )

    tokens = await runtime.auth.exchange_code(
        origin="https://bisheng.example.com",
        code=code,
        client_id="web-app",
        redirect_uri="https://web.example.com/callback",
        code_verifier=verifier,
        client_secret=created.client_secret,
    )
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.id_token

    # Verify id_token via published JWKS public key
    jwks = await runtime.keys.get_jwks()
    assert len(jwks["keys"]) == 1
    pub_key = jwt.algorithms.ECAlgorithm.from_jwk(jwks["keys"][0])
    id_claims = jwt.decode(tokens.id_token, pub_key, algorithms=["ES256"], audience="web-app")
    assert id_claims["sub"] == "42"
    assert id_claims["preferred_username"] == "alice"
    assert id_claims["email"] == "alice@example.com"
    assert id_claims["nonce"] == "nonce-xyz"
    assert id_claims["tenant_id"] == "7"

    # Replaying consumed authorization code fails
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.auth.exchange_code(
            origin="https://bisheng.example.com",
            code=code,
            client_id="web-app",
            redirect_uri="https://web.example.com/callback",
            code_verifier=verifier,
            client_secret=created.client_secret,
        )

    # UserInfo with Bearer access_token
    info = await runtime.auth.userinfo(f"Bearer {tokens.access_token}")
    assert info.sub == "42"
    assert info.preferred_username == "alice"
    assert info.tenant_name == "Acme Corp"

    # Refresh token rotation
    refreshed = await runtime.auth.refresh_access_token(
        origin="https://bisheng.example.com",
        refresh_token=tokens.refresh_token,
        client_id="web-app",
        client_secret=created.client_secret,
    )
    assert refreshed.refresh_token != tokens.refresh_token
    assert refreshed.access_token != tokens.access_token

    # Replaying old refresh token triggers session-wide revocation
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example.com",
            refresh_token=tokens.refresh_token,
            client_id="web-app",
            client_secret=created.client_secret,
        )
    # The successor refresh token is now revoked too
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example.com",
            refresh_token=refreshed.refresh_token,
            client_id="web-app",
            client_secret=created.client_secret,
        )


async def test_pkce_failure_and_invalid_redirect(oauth2_env):
    runtime, _ = oauth2_env
    await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="spa-client",
            client_name="SPA",
            client_type="public",
            redirect_uris=["https://spa.example.com/cb"],
            require_pkce=True,
        )
    )
    _, challenge = _make_pkce("correct-" + "x" * 56)

    with pytest.raises(OAuth2InvalidRedirectUriError):
        await runtime.auth.start_authorization(
            client_id="spa-client",
            redirect_uri="https://evil.example.com/cb",
            response_type="code",
            scope="openid",
            state="s1",
            code_challenge=challenge,
            code_challenge_method="S256",
            nonce=None,
        )

    req_id, _, _ = await runtime.auth.start_authorization(
        client_id="spa-client",
        redirect_uri="https://spa.example.com/cb",
        response_type="code",
        scope="openid",
        state="s1",
        code_challenge=challenge,
        code_challenge_method="S256",
        nonce=None,
    )
    consent = await runtime.auth.submit_consent(request_id=req_id, user_id=42, tenant_id=1, decision="approve")
    code = parse_qs(urlsplit(consent.redirect_uri).query)["code"][0]

    with pytest.raises(OAuth2PkceVerificationFailedError):
        await runtime.auth.exchange_code(
            origin="https://bisheng.example.com",
            code=code,
            client_id="spa-client",
            redirect_uri="https://spa.example.com/cb",
            code_verifier="wrong-" + "y" * 56,
            client_secret=None,
        )


async def test_dsh_authorization_delegates_to_oauth2_client(oauth2_env):
    runtime, redis = oauth2_env
    _, challenge = _make_pkce("dsh-verifier-" + "z" * 50)
    dsh_auth = DshAuthorizationService(redis, "https://bisheng.example.com", oauth2_clients=runtime.clients)

    req = AuthorizationRequest(
        client_id="dsh-desktop",
        redirect_uri="http://127.0.0.1:45678/dsh/callback",
        code_challenge=challenge,
        code_challenge_method="S256",
        state="s" * 40,
    )
    created = await dsh_auth.create(req)
    resolved = await dsh_auth.resolve(created["auth_id"])
    assert resolved["require_consent"] is True
    assert resolved["client_name"] == "BiSheng Desktop (DSH)"

    # Toggling require_consent=False on built-in dsh-desktop propagates to DSH
    await runtime.clients.update_client(BUILTIN_DSH_CLIENT_ID, OAuth2ClientUpdate(require_consent=False))
    created2 = await dsh_auth.create(req)
    resolved2 = await dsh_auth.resolve(created2["auth_id"])
    assert resolved2["require_consent"] is False

    # Disabling dsh-desktop blocks DSH login
    await runtime.clients.update_client(BUILTIN_DSH_CLIENT_ID, OAuth2ClientUpdate(enabled=False))
    with pytest.raises(DshDshDisabledError):
        await dsh_auth.create(req)

    # Re-enable and verify non-registered redirect URI is rejected
    await runtime.clients.update_client(BUILTIN_DSH_CLIENT_ID, OAuth2ClientUpdate(enabled=True))
    bad_req = AuthorizationRequest(
        client_id="dsh-desktop",
        redirect_uri="https://evil.example.com/dsh/callback",
        code_challenge=challenge,
        code_challenge_method="S256",
        state="s" * 40,
    )
    with pytest.raises(DshInvalidRequestError):
        await dsh_auth.create(bad_req)


def test_http_endpoints_discovery_jwks_and_admin_api(oauth2_env):
    runtime, _ = oauth2_env
    app = FastAPI()
    app.include_router(well_known_router)
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(consent_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")

    from types import SimpleNamespace

    fake_user = SimpleNamespace(user_id=1, user_name="admin", tenant_id=1, role="admin", is_global_super=True)
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    app.dependency_overrides[require_super_admin] = lambda: fake_user
    app.dependency_overrides[UserPayload.get_login_user] = lambda: fake_user

    client = TestClient(app)

    meta = client.get("/.well-known/openid-configuration")
    assert client.get("/.well-known/oauth-authorization-server").json() == meta.json()
    assert meta.status_code == 200
    body = meta.json()
    assert body["authorization_endpoint"].endswith("/api/v1/oauth2/authorize")
    assert body["token_endpoint"].endswith("/api/v1/oauth2/token")
    assert body["jwks_uri"].endswith("/api/v1/oauth2/jwks")

    jwks = client.get("/api/v1/oauth2/jwks")
    assert jwks.status_code == 200
    assert jwks.json()["keys"][0]["alg"] == "ES256"

    listed = client.get("/api/v1/oauth2/clients")
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["data"][0]["client_id"] == BUILTIN_DSH_CLIENT_ID


async def _issue_security_tokens(runtime, *, scope="openid offline_access", client_type="public"):
    created = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="security-client",
            client_name="Security",
            client_type=client_type,
            redirect_uris=["https://security.example/cb"],
        )
    )
    verifier, challenge = _make_pkce()
    request_id, _, _ = await runtime.auth.start_authorization(
        client_id=created.client.client_id,
        redirect_uri="https://security.example/cb",
        response_type="code",
        scope=scope,
        state=None,
        code_challenge=challenge,
        code_challenge_method="S256",
        nonce=None,
    )
    result = await runtime.auth.submit_consent(request_id=request_id, user_id=42, tenant_id=7, decision="approve")
    code = parse_qs(urlsplit(result.redirect_uri).query)["code"][0]
    tokens = await runtime.auth.exchange_code(
        origin="https://bisheng.example",
        code=code,
        client_id=created.client.client_id,
        redirect_uri="https://security.example/cb",
        code_verifier=verifier,
        client_secret=created.client_secret,
    )
    return tokens, created.client_secret


@pytest.mark.parametrize(
    "scope,profile,email", [("openid", False, False), ("openid profile", True, False), ("openid email", False, True)]
)
async def test_userinfo_respects_granted_scopes(oauth2_env, scope, profile, email):
    runtime, _ = oauth2_env
    tokens, _ = await _issue_security_tokens(runtime, scope=scope)
    body = (await runtime.auth.userinfo(f"Bearer {tokens.access_token}")).model_dump(exclude_none=True)
    assert ("name" in body) is profile
    assert ("preferred_username" in body) is profile
    assert ("email" in body) is email
    assert body["sub"] == "42"


@pytest.mark.parametrize("kind", ["access_token", "refresh_token"])
async def test_confidential_revocation_authenticates_and_matches_owner(oauth2_env, kind):
    runtime, _ = oauth2_env
    tokens, secret = await _issue_security_tokens(runtime, client_type="confidential")
    token = getattr(tokens, kind)
    for credentials in [
        {},
        {"client_id": "security-client"},
        {"client_id": "security-client", "client_secret": "wrong"},
        {"client_id": BUILTIN_DSH_CLIENT_ID},
    ]:
        with pytest.raises(OAuth2InvalidClientAuthError):
            await runtime.auth.revoke_token(token=token, **credentials)
        assert (await runtime.auth.userinfo(f"Bearer {tokens.access_token}")).sub == "42"
    await runtime.auth.revoke_token(token=token, client_id="security-client", client_secret=secret)
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example",
            refresh_token=tokens.refresh_token,
            client_id="security-client",
            client_secret=secret,
        )


async def test_concurrent_refresh_replay_revokes_winner_family(oauth2_env, monkeypatch):
    from sqlmodel import select

    from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository

    runtime, _ = oauth2_env
    tokens, _ = await _issue_security_tokens(runtime)
    original = runtime.auth._identity_lookup
    ready = asyncio.Event()
    arrivals = 0

    async def both_loaded(tenant_id, user_id):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        return await original(tenant_id, user_id)

    monkeypatch.setattr(runtime.auth, "_identity_lookup", both_loaded)
    results = await asyncio.gather(
        *[
            runtime.auth.refresh_access_token(
                origin="https://bisheng.example",
                refresh_token=tokens.refresh_token,
                client_id="security-client",
                client_secret=None,
            )
            for _ in range(2)
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(r, OAuth2InvalidGrantError) for r in results) == 1, results
    assert sum(not isinstance(r, Exception) for r in results) == 1, results
    with runtime.auth._session_factory() as db:
        repo = OAuth2SessionRepository(db)
        assert repo.get_session(tokens.session_id).state == "REVOKED"
        family = db.exec(select(OAuth2RefreshToken).where(OAuth2RefreshToken.session_id == tokens.session_id)).all()
        assert len(family) == 2
        assert all(row.state == "REVOKED" for row in family)


async def test_revoke_between_refresh_lookup_and_cas_cannot_resurrect(oauth2_env, monkeypatch):
    from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository

    runtime, _ = oauth2_env
    tokens, _ = await _issue_security_tokens(runtime)
    original = runtime.auth._identity_lookup

    async def revoked_after_lookup(tenant_id, user_id):
        await runtime.auth.revoke_token(token=tokens.refresh_token, client_id="security-client")
        return await original(tenant_id, user_id)

    monkeypatch.setattr(runtime.auth, "_identity_lookup", revoked_after_lookup)
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example",
            refresh_token=tokens.refresh_token,
            client_id="security-client",
            client_secret=None,
        )
    with runtime.auth._session_factory() as db:
        assert OAuth2SessionRepository(db).get_session(tokens.session_id).state == "REVOKED"


@pytest.fixture
def real_person_identity(oauth2_env, monkeypatch):
    import bisheng.oauth2_provider.runtime as provider_runtime
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import User

    runtime, _ = oauth2_env
    with runtime.auth._session_factory() as db:
        SQLModel.metadata.create_all(db.get_bind(), tables=[User.__table__, Tenant.__table__, UserTenant.__table__])
        db.add(User(user_id=42, user_name="ordinary", password="unused", token_version=3))
        db.add(Tenant(id=7, tenant_code="acme", tenant_name="Acme"))
        db.add(UserTenant(user_id=42, tenant_id=7, status="active", is_active=1))
    monkeypatch.setattr(provider_runtime, "oauth2_db_session", runtime.auth._session_factory)
    monkeypatch.setattr(runtime.auth, "_identity_lookup", provider_runtime.lookup_user_identity)
    return runtime


@pytest.mark.parametrize(
    "change", ["removed", "disabled_membership", "historical", "disabled_tenant", "disabled_user", "missing_human"]
)
async def test_real_identity_rejects_removed_or_inactive_person(real_person_identity, change):
    from sqlalchemy import delete, update

    from bisheng.common.errcode.oauth2_provider import OAuth2UserInactiveError
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import User

    runtime = real_person_identity
    tokens, _ = await _issue_security_tokens(runtime)
    identity = await runtime.auth._identity_lookup(7, 42)
    assert identity.active and identity.tenant_name == "Acme"
    assert await runtime.auth._identity_lookup(1, 42) is None
    with runtime.auth._session_factory() as db:
        if change == "removed":
            db.execute(delete(UserTenant))
        elif change == "disabled_membership":
            db.execute(update(UserTenant).values(status="disabled"))
        elif change == "historical":
            db.execute(update(UserTenant).values(is_active=None))
        elif change == "disabled_tenant":
            db.execute(update(Tenant).values(status="disabled"))
        elif change == "disabled_user":
            db.execute(update(User).values(delete=1))
        else:
            # A membership alone, including a service-account ID, is not a person.
            db.execute(delete(User))
    with pytest.raises(OAuth2UserInactiveError):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example",
            refresh_token=tokens.refresh_token,
            client_id="security-client",
            client_secret=None,
        )


@pytest.mark.parametrize("version,expected", [(3, True), (2, False), (None, False)])
async def test_autoapproval_uses_full_browser_validation(real_person_identity, monkeypatch, version, expected):
    from starlette.requests import Request

    import bisheng.user.domain.services.jwt_secret as jwt_secrets
    import bisheng.utils.http_middleware as middleware
    from bisheng.oauth2_provider.api.endpoints.oidc import _try_browser_user
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.services.auth import AuthJwt

    monkeypatch.setattr(jwt_secrets, "resolve_jwt_secret", lambda: "test-only-oauth-browser-signing-secret")
    auth = AuthJwt()
    subject = {"user_id": 42, "user_name": "ordinary", "tenant_id": 7}
    if version is not None:
        subject["token_version"] = version
    token = auth.create_access_token(subject)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/api/v1/oauth2/authorize",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )

    async def current_version(*args):
        return 3

    async def current_session(*args):
        return True

    async def ordinary_user(*args):
        from types import SimpleNamespace

        return SimpleNamespace(delete=0)

    async def ordinary_login(**kwargs):
        return UserPayload(
            user_id=42, user_name="ordinary", user_role=[], tenant_id=7, token_version=3, is_global_super=False
        )

    async def not_super(*args):
        return False

    monkeypatch.setattr(UserDao, "aget_token_version", current_version)
    monkeypatch.setattr(UserDao, "aget_user", ordinary_user)
    monkeypatch.setattr(middleware, "_validate_current_session_token", current_session)
    monkeypatch.setattr(middleware, "_check_is_global_super", not_super)
    monkeypatch.setattr(UserPayload, "init_login_user", ordinary_login)
    result = await _try_browser_user(request)
    assert result == ((7, 42) if expected else None)


async def test_revoke_waits_for_rotation_and_revokes_committed_successor(oauth2_env, monkeypatch):
    from threading import Event

    from sqlmodel import select

    from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository

    runtime, _ = oauth2_env
    tokens, _ = await _issue_security_tokens(runtime)
    rotated = Event()
    revoking = Event()
    original_rotate = OAuth2SessionRepository.rotate_refresh_token
    original_revoke = OAuth2SessionRepository.revoke_session

    def held_rotation(self, **kwargs):
        result = original_rotate(self, **kwargs)
        rotated.set()
        assert revoking.wait(5), "revocation did not reach the locked family"
        return result  # The session context commits only after this return.

    def waiting_revoke(self, *args, **kwargs):
        revoking.set()
        return original_revoke(self, *args, **kwargs)

    monkeypatch.setattr(OAuth2SessionRepository, "rotate_refresh_token", held_rotation)
    monkeypatch.setattr(OAuth2SessionRepository, "revoke_session", waiting_revoke)
    refresh = asyncio.create_task(
        runtime.auth.refresh_access_token(
            origin="https://bisheng.example",
            refresh_token=tokens.refresh_token,
            client_id="security-client",
            client_secret=None,
        )
    )
    assert await asyncio.to_thread(rotated.wait, 5)
    await runtime.auth.revoke_token(token=tokens.refresh_token, client_id="security-client")
    await refresh
    with runtime.auth._session_factory() as db:
        assert OAuth2SessionRepository(db).get_session(tokens.session_id).state == "REVOKED"
        family = db.exec(select(OAuth2RefreshToken).where(OAuth2RefreshToken.session_id == tokens.session_id)).all()
        assert len(family) == 2 and all(row.state == "REVOKED" for row in family)


async def test_failed_successor_write_rolls_back_consumption(oauth2_env, monkeypatch):
    from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository
    from bisheng.oauth2_provider.domain.services.auth_service import _sha256_hex

    runtime, _ = oauth2_env
    tokens, _ = await _issue_security_tokens(runtime)
    original_add = Session.add

    def reject_successor(self, instance, *args, **kwargs):
        if isinstance(instance, OAuth2RefreshToken) and instance.generation == 2:
            raise RuntimeError("successor write failure")
        return original_add(self, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "add", reject_successor)
    with pytest.raises(RuntimeError, match="successor write failure"):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example",
            refresh_token=tokens.refresh_token,
            client_id="security-client",
            client_secret=None,
        )
    with runtime.auth._session_factory() as db:
        repo = OAuth2SessionRepository(db)
        assert repo.get_refresh_token(_sha256_hex(tokens.refresh_token)).state == "ACTIVE"
        assert repo.get_session(tokens.session_id).state == "ACTIVE"


async def test_tenant_removal_between_consent_and_exchange_blocks_token(real_person_identity):
    from sqlalchemy import delete

    from bisheng.common.errcode.oauth2_provider import OAuth2UserInactiveError
    from bisheng.database.models.tenant import UserTenant

    runtime = real_person_identity
    client = await runtime.clients.get_active_client_model(BUILTIN_DSH_CLIENT_ID)
    await runtime.auth.code_store.save_code(
        "before-removal",
        {
            "client_id": BUILTIN_DSH_CLIENT_ID,
            "client_registration_id": client.id,
            "redirect_uri": "http://127.0.0.1/dsh/callback",
            "tenant_id": 7,
            "user_id": 42,
            "scopes": ["openid"],
            "code_challenge": _make_pkce()[1],
        },
    )
    with runtime.auth._session_factory() as db:
        db.execute(delete(UserTenant))
    with pytest.raises(OAuth2UserInactiveError):
        await runtime.auth.exchange_code(
            origin="https://bisheng.example",
            code="before-removal",
            client_id=BUILTIN_DSH_CLIENT_ID,
            redirect_uri="http://127.0.0.1/dsh/callback",
            code_verifier=_make_pkce()[0],
            client_secret=None,
        )
