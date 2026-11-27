"""Exchange integration tests with SQLite and isolated provider fixtures."""

import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import (
    OAuth2InvalidAccessTokenError,
    OAuth2InvalidGrantError,
    OAuth2InvalidScopeError,
    OAuth2InvalidTargetError,
)
from bisheng.oauth2_provider.api.endpoints.exchange import admin_router, require_global_admin
from bisheng.oauth2_provider.api.endpoints.oidc import public_router
from bisheng.oauth2_provider.domain.models.exchange import OAuth2ExchangePolicy, OAuth2ExchangeSession
from bisheng.oauth2_provider.domain.models.session import OAuth2RefreshToken, OAuth2Session
from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientCreate, OAuth2ClientUpdate
from bisheng.oauth2_provider.domain.schemas.exchange import (
    ACCESS_TOKEN_TYPE,
    EXCHANGE_GRANT_TYPE,
    OAuth2ExchangePolicyUpdate,
)
from bisheng.oauth2_provider.domain.services.exchange_service import OAuth2ExchangeService
from bisheng.oauth2_provider.runtime import get_oauth2_runtime
from test.oauth2_provider.test_oauth2_provider import oauth2_env  # noqa: F401

ORIGIN = "https://bisheng.example.com"


@pytest.fixture
async def exchange_env(request):
    runtime, _ = request.getfixturevalue("oauth2_env")
    with runtime.auth._session_factory() as db:
        SQLModel.metadata.create_all(
            db.get_bind(), tables=[OAuth2ExchangePolicy.__table__, OAuth2ExchangeSession.__table__]
        )
    exchange = OAuth2ExchangeService(
        clients=runtime.clients,
        keys=runtime.keys,
        session_factory=runtime.auth._session_factory,
        identity_lookup=runtime.auth._identity_lookup,
    )
    runtime.exchange = exchange
    runtime.auth._exchange_validator = exchange.validate_exchange_claims
    a = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="source-a",
            client_name="Source",
            redirect_uris=["https://a.example/cb"],
            grant_types=["authorization_code", "refresh_token", EXCHANGE_GRANT_TYPE],
        )
    )
    b = await runtime.clients.create_client(
        OAuth2ClientCreate(client_id="target-b", client_name="Target", redirect_uris=["https://b.example/cb"])
    )
    policy = OAuth2ExchangePolicyUpdate(allowed_scopes=["openid", "profile"])
    await exchange.put_policy("source-a", "target-b", policy, 1)
    verifier = "a" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    request_id, _, _ = await runtime.auth.start_authorization(
        client_id="source-a",
        redirect_uri="https://a.example/cb",
        response_type="code",
        scope="openid profile email offline_access",
        state="s",
        code_challenge=challenge,
        code_challenge_method="S256",
        nonce="n",
    )
    consent = await runtime.auth.submit_consent(request_id=request_id, user_id=42, tenant_id=7, decision="approve")
    code = parse_qs(urlsplit(consent.redirect_uri).query)["code"][0]
    tokens = await runtime.auth.exchange_code(
        origin=ORIGIN,
        code=code,
        client_id="source-a",
        client_secret=a.client_secret,
        redirect_uri="https://a.example/cb",
        code_verifier=verifier,
    )
    params = {
        "origin": ORIGIN,
        "client_id": "source-a",
        "client_secret": a.client_secret,
        "subject_token": tokens.access_token,
        "subject_token_type": ACCESS_TOKEN_TYPE,
        "audience": "target-b",
        "scope": "openid profile",
    }
    return runtime, params, tokens, b.client_secret


async def test_lifecycle_independent_revoke_and_parent_revocation(exchange_env):
    """AC-01/08/14/15: real code issuance, exchange, B verification and directional revocation."""
    runtime, params, parent, secret_b = exchange_env
    result = await runtime.exchange.exchange_token(**params)
    assert not {"id_token", "refresh_token", "refresh_expires_in"} & result.keys()
    keys = await runtime.keys.get_jwks()
    public = jwt.PyJWK.from_dict(keys["keys"][0]).key
    claims = jwt.decode(result["access_token"], public, algorithms=["ES256"], audience="target-b", issuer=ORIGIN)
    assert claims["sub"] == "42" and claims["tenant_id"] == "7"
    assert claims["aud"] == "target-b" and claims["exp"] <= claims["iat"] + 300
    assert claims["session_id"] != parent.session_id
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(result["access_token"], public, algorithms=["ES256"], audience="source-a")
    assert (await runtime.auth.userinfo("Bearer " + result["access_token"])).sub == "42"
    with runtime.auth._session_factory() as db:
        assert (
            db.exec(select(OAuth2RefreshToken).where(OAuth2RefreshToken.session_id == result["session_id"])).first()
            is None
        )
    await runtime.auth.revoke_token(token=result["access_token"], client_id="target-b", client_secret=secret_b)
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + result["access_token"])
    assert (await runtime.auth.userinfo("Bearer " + parent.access_token)).sub == "42"
    second = await runtime.exchange.exchange_token(**params)
    await runtime.auth.revoke_token(
        token=parent.access_token, client_id="source-a", client_secret=params["client_secret"]
    )
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + second["access_token"])
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.exchange.exchange_token(**params)


@pytest.mark.parametrize("scope", ["", "openid email", "dsh", "offline_access", "profile admin"])
async def test_scope_is_whole_request_denial(exchange_env, scope):
    """AC-06/07: disallowed scopes are rejected without silently narrowing."""
    runtime, params, _, _ = exchange_env
    with pytest.raises(OAuth2InvalidScopeError):
        await runtime.exchange.exchange_token(**{**params, "scope": scope})


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "https://evil.example"),
        ("aud", "other"),
        ("tenant_id", "8"),
        ("sub", "43"),
        ("token_use", "id"),
        ("exp", 1),
        ("token_exchange", True),
    ],
)
async def test_signed_but_invalid_subject_claims(exchange_env, field, value):
    """AC-04/05: a valid signature does not replace issuer/audience/identity validation."""
    runtime, params, _, _ = exchange_env
    claims = jwt.decode(params["subject_token"], options={"verify_signature": False})
    claims[field] = value
    token = jwt.encode(claims, await runtime.keys.get_private_key(), algorithm="ES256")
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.exchange.exchange_token(**{**params, "subject_token": token})


async def test_policy_updates_and_child_online_scope_check(exchange_env):
    """AC-03/10/15: policy changes affect new exchanges and existing online checks."""
    runtime, params, _, _ = exchange_env
    result = await runtime.exchange.exchange_token(**params)
    await runtime.exchange.put_policy("source-a", "target-b", OAuth2ExchangePolicyUpdate(allowed_scopes=["openid"]), 1)
    with pytest.raises(OAuth2InvalidScopeError):
        await runtime.exchange.exchange_token(**params)
    with pytest.raises(OAuth2InvalidAccessTokenError):
        await runtime.auth.userinfo("Bearer " + result["access_token"])
    await runtime.exchange.put_policy(
        "source-a", "target-b", OAuth2ExchangePolicyUpdate(allowed_scopes=["openid"], enabled=False), 1
    )
    with pytest.raises(OAuth2InvalidTargetError):
        await runtime.exchange.exchange_token(**{**params, "scope": "openid"})


async def test_identity_failure_and_dependency_outage(exchange_env):
    """AC-04/12: inactive identity and failed dependencies never issue tokens."""
    runtime, params, _, _ = exchange_env

    async def inactive(*args):
        return None

    runtime.exchange._identity_lookup = inactive
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.exchange.exchange_token(**params)

    async def outage(*args):
        raise RuntimeError("sensitive-test-token")

    runtime.exchange._identity_lookup = outage
    with pytest.raises(BaseErrorCode) as exc:
        await runtime.exchange.exchange_token(**params)
    assert exc.value.code == 28117 and "sensitive-test-token" not in str(exc.value)


async def test_http_strict_exchange_and_legacy(exchange_env):
    """AC-02/16/17: wire behavior, duplicate fields and old grant compatibility."""
    runtime, params, _, _ = exchange_env
    app = FastAPI()
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    payload = {k: v for k, v in params.items() if k != "origin"}
    payload["grant_type"] = EXCHANGE_GRANT_TYPE
    headers = {"Host": "bisheng.example.com", "X-Forwarded-Proto": "https"}
    with TestClient(app, base_url=ORIGIN) as client:
        r = client.post("/api/v1/oauth2/token", data=payload, headers=headers)
        assert r.status_code == 200 and r.json()["issued_token_type"] == ACCESS_TOKEN_TYPE
        assert "no-store" in r.headers["cache-control"]
        for body in [
            urlencode(payload) + "&audience=another",
            urlencode(payload) + "&actor_token=bad",
            urlencode(payload) + "&tenant_id=8",
        ]:
            r = client.post(
                "/api/v1/oauth2/token",
                content=body,
                headers={**headers, "content-type": "application/x-www-form-urlencoded"},
            )
            assert r.status_code == 400 and r.json()["error"] == "invalid_request"
        r = client.post("/api/v1/oauth2/token", json={**payload, "client_secret": "bad"}, headers=headers)
        assert r.status_code == 401 and r.json()["error"] == "invalid_client"
        r = client.post("/api/v1/oauth2/token", data={"grant_type": "bad"})
        assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    with pytest.raises(Exception) as rejected:
        await require_global_admin(SimpleNamespace(is_global_super=False))
    assert rejected.value.status_code == 403


async def test_fixed_start_deadline(exchange_env, monkeypatch):
    """AC-08: lookup processing consumes the original lifetime budget."""
    import time

    import bisheng.oauth2_provider.domain.services.exchange_service as service

    runtime, params, _, _ = exchange_env
    original = runtime.exchange._identity_lookup
    clock = [int(time.time())]
    monkeypatch.setattr(service.time, "time", lambda: clock[0])

    async def slow(tenant, user):
        clock[0] += 250
        return await original(tenant, user)

    runtime.exchange._identity_lookup = slow
    result = await runtime.exchange.exchange_token(**params)
    assert 0 < result["expires_in"] <= 50


@pytest.mark.parametrize("token_name", ["id_token", "refresh_token"])
async def test_other_credential_types_rejected(exchange_env, token_name):
    """AC-05: ID and refresh credentials are not access-token subjects."""
    runtime, params, parent, _ = exchange_env
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.exchange.exchange_token(**{**params, "subject_token": getattr(parent, token_name)})


async def test_commit_failure_rolls_back(exchange_env):
    """AC-12: failure before commit rolls back both child and link."""
    from contextlib import contextmanager

    runtime, params, _, _ = exchange_env
    factory = runtime.exchange._session_factory

    @contextmanager
    def failing():
        with factory() as db:
            yield db
            if db.exec(select(OAuth2ExchangeSession)).first():
                raise RuntimeError("commit unavailable")

    runtime.exchange._session_factory = failing
    with pytest.raises(BaseErrorCode) as exc:
        await runtime.exchange.exchange_token(**params)
    assert exc.value.code == 28117
    with factory() as db:
        assert db.exec(select(OAuth2ExchangeSession)).first() is None
        assert db.exec(select(OAuth2Session).where(OAuth2Session.client_id == "target-b")).first() is None


async def test_client_and_parent_scope_denials(exchange_env):
    """AC-02/03/06: current client/session facts bound allowed exchanges."""
    runtime, params, parent, _ = exchange_env
    await runtime.clients.update_client(
        "source-a", OAuth2ClientUpdate(grant_types=["authorization_code", "refresh_token"])
    )
    with pytest.raises(BaseErrorCode) as exc:
        await runtime.exchange.exchange_token(**params)
    assert exc.value.code == 28116
    await runtime.clients.update_client(
        "source-a", OAuth2ClientUpdate(grant_types=["authorization_code", "refresh_token", EXCHANGE_GRANT_TYPE])
    )
    await runtime.clients.update_client("target-b", OAuth2ClientUpdate(enabled=False))
    with pytest.raises(OAuth2InvalidTargetError):
        await runtime.exchange.exchange_token(**params)
    await runtime.clients.update_client("target-b", OAuth2ClientUpdate(enabled=True))
    with runtime.auth._session_factory() as db:
        row = db.exec(select(OAuth2Session).where(OAuth2Session.session_id == parent.session_id)).one()
        row.scope = "openid"
        db.add(row)
    with pytest.raises(OAuth2InvalidScopeError):
        await runtime.exchange.exchange_token(**params)


async def test_policy_admin_http_boundary(exchange_env):
    """AC-10/11: only global administrators can list trust policies."""
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.main import _EXCEPTION_HANDLERS

    runtime, _, _, _ = exchange_env
    app = FastAPI(exception_handlers=_EXCEPTION_HANDLERS)
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    for global_super in (False, True):
        app.dependency_overrides[UserPayload.get_login_user] = lambda flag=global_super: SimpleNamespace(
            is_global_super=flag, user_id=1
        )
        with TestClient(app) as client:
            r = client.get("/api/v1/oauth2/exchange-policies?page_size=1")
            data = r.json()
            assert r.status_code == 200
            assert data["status_code"] == (200 if global_super else 403)
            if global_super:
                assert data["data"]["total"] == 1


async def test_duplicate_json_basic_mixing_and_limits(exchange_env):
    """AC-16: ambiguous credentials, duplicate JSON and oversized inputs fail."""
    import json

    runtime, params, _, _ = exchange_env
    payload = {k: v for k, v in params.items() if k != "origin"}
    payload["grant_type"] = EXCHANGE_GRANT_TYPE
    app = FastAPI()
    app.include_router(public_router, prefix="/api/v1")
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    with TestClient(app, base_url=ORIGIN) as client:
        for body in [
            json.dumps(payload)[:-1] + ',"audience":"target-b"}',
            json.dumps({**payload, "subject_token": "x" * 16385}),
            json.dumps({**payload, "scope": ["openid"]}),
        ]:
            r = client.post("/api/v1/oauth2/token", content=body, headers={"content-type": "application/json"})
            assert r.status_code == 400 and r.json()["error"] == "invalid_request"
        r = client.post("/api/v1/oauth2/token", data=payload, auth=("source-a", params["client_secret"]))
        assert r.status_code == 400 and r.json()["error"] == "invalid_request"
        payload.pop("client_id")
        payload.pop("client_secret")
        r = client.post("/api/v1/oauth2/token", data=payload, auth=("source-a", params["client_secret"]))
        assert r.status_code == 200
