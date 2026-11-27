"""AC-18..23: real platform sessions, provider signing, consent and HTTP exchange."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import OAuth2ConsentRequiredError, OAuth2InvalidAccessTokenError
from bisheng.oauth2_provider.api.endpoints.oidc import consent_router, public_router
from bisheng.oauth2_provider.domain.models.platform_exchange import OAuth2PlatformExchangeSession, OAuth2UserConsent
from bisheng.oauth2_provider.domain.models.session import OAuth2RefreshToken
from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientCreate, OAuth2ClientUpdate
from bisheng.oauth2_provider.domain.schemas.exchange import ACCESS_TOKEN_TYPE, EXCHANGE_GRANT_TYPE
from bisheng.oauth2_provider.domain.schemas.platform_exchange import PLATFORM_SESSION_TOKEN_TYPE
from bisheng.oauth2_provider.domain.services.exchange_service import OAuth2ExchangeService
from bisheng.oauth2_provider.domain.services.platform_exchange_service import OAuth2PlatformExchangeService
from bisheng.oauth2_provider.runtime import get_oauth2_runtime
from bisheng.user.application.oauth_exchange import read_platform_exchange_subject
from test.oauth2_provider.test_oauth2_provider import oauth2_env  # noqa: F401
from test.platform_auth.test_oauth_exchange_seam import request as source_request
from test.platform_auth.test_platform_session import runtime as source_runtime

ORIGIN = "https://bisheng.example.com"


@pytest.fixture
async def platform_env(request, tmp_path):
    runtime, _ = request.getfixturevalue("oauth2_env")
    source, clock, identity = source_runtime.__wrapped__(tmp_path)
    clock[0] = datetime.now(UTC).replace(tzinfo=None)
    with runtime.auth._session_factory() as db:
        SQLModel.metadata.create_all(
            db.get_bind(), tables=[OAuth2PlatformExchangeSession.__table__, OAuth2UserConsent.__table__]
        )
    service = OAuth2PlatformExchangeService(
        keys=runtime.keys,
        session_factory=runtime.auth._session_factory,
        identity_lookup=runtime.auth._identity_lookup,
        platform_validator=source.validate_reference,
    )
    runtime.platform_exchange = service
    runtime.exchange = OAuth2ExchangeService(
        clients=runtime.clients,
        keys=runtime.keys,
        session_factory=runtime.auth._session_factory,
        identity_lookup=runtime.auth._identity_lookup,
    )
    runtime.exchange._platform_validator = service.validate_claims
    runtime.auth._exchange_validator = runtime.exchange.validate_exchange_claims
    runtime.auth._consent_recorder = service.record_consent
    registered = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="platform-target",
            client_name="B",
            redirect_uris=["https://b.example/cb"],
            grant_types=["authorization_code", EXCHANGE_GRANT_TYPE],
            require_consent=False,
        )
    )
    runtime.target_secret = registered.client_secret
    token = await source.issue(7, 9, "bisheng-mobile")
    subject = await read_platform_exchange_subject(source_request(source), token["access_token"])
    app = FastAPI()
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(consent_router, prefix="/api/v1")
    app.state.platform_auth_service = source
    app.state.platform_auth_settings = SimpleNamespace(public_origin=ORIGIN)
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=7, tenant_id=9, is_global_super=False
    )
    return runtime, source, clock, identity, token, subject, app


async def exchange(env, **kwargs):
    runtime, _, _, _, _, subject, _ = env
    return await runtime.platform_exchange.exchange(
        origin=ORIGIN,
        subject=kwargs.pop("subject", subject),
        audience="platform-target",
        scope=kwargs.pop("scope", "openid profile"),
        **kwargs,
    )


async def approve(runtime, scope="openid profile", decision="approve", direct=False):
    verifier = "z" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    rid, _, _ = await runtime.auth.start_authorization(
        client_id="platform-target",
        redirect_uri="https://b.example/cb",
        response_type="code",
        scope=scope,
        state="first-party",
        nonce=None,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    if direct:
        await runtime.auth.approve_request_direct(request_id=rid, user_id=7, tenant_id=9)
    else:
        await runtime.auth.submit_consent(request_id=rid, user_id=7, tenant_id=9, decision=decision)


async def test_silent_without_any_source_client_or_pair_policy(platform_env):
    runtime, source, _, _, token, _, _ = platform_env
    result = await exchange(platform_env)
    assert result["issued_token_type"] == ACCESS_TOKEN_TYPE and 0 < result["expires_in"] <= 300
    assert "refresh_token" not in result and "id_token" not in result
    key = await runtime.keys.get_public_key()
    claims = jwt.decode(result["access_token"], key, algorithms=["ES256"], issuer=ORIGIN, audience="platform-target")
    assert (claims["sub"], claims["tenant_id"], claims["client_id"]) == ("7", "9", "bisheng-mobile")
    assert claims["exchange_source"] == "platform_session"
    assert token["access_token"] not in str(claims)
    info = await runtime.auth.userinfo("Bearer " + result["access_token"])
    assert info.sub == "7"
    with runtime.auth._session_factory() as db:
        assert db.exec(select(OAuth2RefreshToken)).all() == []
        assert db.exec(select(OAuth2UserConsent)).all() == []
        link = db.exec(select(OAuth2PlatformExchangeSession)).one()
        assert token["access_token"] not in str(link.source_reference)
    await runtime.auth.revoke_token(
        token=result["access_token"], client_id="platform-target", client_secret=runtime.target_secret
    )
    await source.inspect(token["access_token"])


@pytest.mark.parametrize("change", ["logout", "token_version", "member", "session_expiry"])
async def test_parent_revocation_is_online_enforced(platform_env, change):
    runtime, source, clock, identity, token, _, _ = platform_env
    result = await exchange(platform_env)
    if change == "logout":
        await source.logout(token["access_token"])
    elif change == "token_version":
        identity["token_version"] += 1
    elif change == "member":
        identity.clear()  # No authoritative user/membership facts remain.
    else:
        clock[0] += timedelta(days=91)
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + result["access_token"])


@pytest.mark.parametrize(
    "update",
    [
        {"enabled": False},
        {"grant_types": ["authorization_code"]},
        {"allowed_scopes": ["openid"]},
        {"require_consent": True},
    ],
)
async def test_current_target_state_is_enforced(platform_env, update):
    runtime, *_ = platform_env
    result = await exchange(platform_env)
    await runtime.clients.update_client("platform-target", OAuth2ClientUpdate(**update))
    with pytest.raises(BaseErrorCode):
        await exchange(platform_env)
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + result["access_token"])


async def test_explicit_user_consent_scope_and_revocation(platform_env):
    runtime, *_ = platform_env
    await runtime.clients.update_client("platform-target", OAuth2ClientUpdate(require_consent=True))
    with pytest.raises(OAuth2ConsentRequiredError):
        await exchange(platform_env)
    await approve(runtime, "openid", decision="deny")
    with pytest.raises(OAuth2ConsentRequiredError):
        await exchange(platform_env)
    await approve(runtime, "openid", direct=True)
    with pytest.raises(OAuth2ConsentRequiredError):
        await exchange(platform_env, scope="openid")
    await approve(runtime, "openid")
    await exchange(platform_env, scope="openid")
    with pytest.raises(OAuth2ConsentRequiredError):
        await exchange(platform_env)
    await approve(runtime, "openid profile")
    result = await exchange(platform_env)
    await runtime.platform_exchange.revoke_consent("platform-target", 7, 8)
    await runtime.auth.userinfo("Bearer " + result["access_token"])
    await runtime.platform_exchange.revoke_consent("platform-target", 7, 9)
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + result["access_token"])


@pytest.mark.parametrize("scope", [None, "", "openid dsh", "offline_access", "admin", "openid email unknown"])
async def test_scope_denies_whole_request(platform_env, scope):
    with pytest.raises(BaseErrorCode) as exc:
        await exchange(platform_env, scope=scope)
    assert exc.value.code == 28106


async def test_parent_access_and_session_cap(platform_env):
    _, source, _, _, token, subject, _ = platform_env
    # Subject timestamps are trusted server values; source verification still uses actual stored reference.
    now = int(datetime.now(UTC).timestamp())
    result = await exchange(platform_env, subject={**subject, "session_expires_at": now + 20})
    assert 0 < result["expires_in"] <= 20
    await source.inspect(token["access_token"])


async def test_http_cookie_bearer_body_and_consent_error(platform_env):
    runtime, source, _, _, token, _, app = platform_env
    data = {
        "grant_type": EXCHANGE_GRANT_TYPE,
        "subject_token_type": PLATFORM_SESSION_TOKEN_TYPE,
        "audience": "platform-target",
        "scope": "openid profile",
    }
    with TestClient(app, base_url=ORIGIN) as client:
        for headers, fields in [
            ({}, {"subject_token": token["access_token"]}),
            ({"Authorization": "Bearer " + token["access_token"]}, {}),
        ]:
            r = client.post("/api/v1/oauth2/token", data={**data, **fields}, headers=headers)
            assert r.status_code == 200, r.text
            assert r.headers["cache-control"] == "no-store"
        bound = await source.issue(7, 9, "bisheng-web")
        sid = bound["session_id"]
        client.cookies.set("platform_session_hint", sid)
        client.cookies.set("platform_access_" + sid, bound["access_token"])
        headers = {"Origin": ORIGIN, "X-CSRF-Token": bound["csrf_token"]}
        r = client.post("/api/v1/oauth2/token", data=data, headers=headers)
        assert r.status_code == 200, r.text
        r = client.post("/api/v1/oauth2/token", data=data)
        assert r.status_code == 400 and r.json()["error"] == "invalid_request"
        await runtime.clients.update_client("platform-target", OAuth2ClientUpdate(require_consent=True))
        r = client.post("/api/v1/oauth2/token", data=data, headers=headers)
        assert r.status_code == 400 and r.json()["error"] == "consent_required"


@pytest.mark.parametrize(
    "extra",
    [{"client_id": "bisheng-web"}, {"client_secret": "forbidden"}, {"tenant_id": "1"}, {"actor_token": "forbidden"}],
)
async def test_http_source_identity_cannot_be_supplied(platform_env, extra):
    *_, token, _, app = platform_env
    with TestClient(app, base_url=ORIGIN) as client:
        r = client.post(
            "/api/v1/oauth2/token",
            data={
                "grant_type": EXCHANGE_GRANT_TYPE,
                "subject_token_type": PLATFORM_SESSION_TOKEN_TYPE,
                "subject_token": token["access_token"],
                "audience": "platform-target",
                "scope": "openid",
                **extra,
            },
        )
        assert r.status_code == 400 and r.json()["error"] == "invalid_request"
