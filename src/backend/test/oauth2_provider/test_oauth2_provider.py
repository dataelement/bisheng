"""End-to-end and unit tests for the OAuth 2.0 / OIDC Provider and DSH client integration."""

from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
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
def oauth2_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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

    meta = client.get("/.well-known/oauth-authorization-server")
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
