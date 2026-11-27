"""AC-20/21/22/23: fault, lifetime and registration replay regressions."""

import base64
import hashlib
import time
from contextlib import contextmanager
from types import SimpleNamespace

import jwt
import pytest
from loguru import logger
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import (
    OAuth2AuthorizationExpiredError,
    OAuth2ConsentRequiredError,
    OAuth2InvalidGrantError,
)
from bisheng.oauth2_provider.domain.models.platform_exchange import OAuth2PlatformExchangeSession, OAuth2UserConsent
from bisheng.oauth2_provider.domain.models.session import OAuth2Session
from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientCreate, OAuth2ClientUpdate
from bisheng.oauth2_provider.domain.schemas.exchange import EXCHANGE_GRANT_TYPE
from bisheng.oauth2_provider.domain.services import platform_exchange_service as module
from test.oauth2_provider.test_platform_exchange import ORIGIN, exchange, oauth2_env, platform_env  # noqa: F401

pytestmark = pytest.mark.usefixtures("platform_env")


async def test_fixed_start_lifetime_consumes_key_lookup_delay(request, monkeypatch):
    env = request.getfixturevalue("platform_env")
    runtime, *_ = env
    now = [int(time.time())]
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: now[0]))
    original = runtime.keys.get_private_key

    async def delayed():
        now[0] += 250
        return await original()

    monkeypatch.setattr(runtime.keys, "get_private_key", delayed)
    result = await exchange(env)
    assert 0 < result["expires_in"] <= 50
    claims = jwt.decode(
        result["access_token"],
        await runtime.keys.get_public_key(),
        algorithms=["ES256"],
        audience="platform-target",
        options={"verify_iat": False},
    )
    assert claims["exp"] - claims["iat"] <= 50


async def test_commit_failure_rolls_back_child_and_link(request, monkeypatch):
    env = request.getfixturevalue("platform_env")
    runtime, *_ = env
    real = runtime.platform_exchange._session_factory

    @contextmanager
    def broken():
        with real() as db:
            yield db
            raise RuntimeError("commit unavailable")

    monkeypatch.setattr(runtime.platform_exchange, "_session_factory", broken)
    with pytest.raises(BaseErrorCode) as exc:
        await exchange(env)
    assert exc.value.code == 28117
    with real() as db:
        assert db.exec(select(OAuth2Session)).all() == []
        assert db.exec(select(OAuth2PlatformExchangeSession)).all() == []


async def test_dependency_value_error_is_safe_unavailable(request, monkeypatch):
    env = request.getfixturevalue("platform_env")
    runtime, *_ = env
    secret = "never-log-private-config-marker"

    async def broken():
        raise ValueError(secret)

    monkeypatch.setattr(runtime.keys, "get_private_key", broken)
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        with pytest.raises(BaseErrorCode) as exc:
            await exchange(env)
        assert exc.value.code == 28117
    finally:
        logger.remove(sink)
    assert secret not in "".join(messages)
    assert env[4]["access_token"] not in "".join(messages)


@pytest.mark.parametrize("phase", ["pending", "code", "existing_consent"])
async def test_reregistered_client_cannot_inherit_old_authorization(request, phase):
    env = request.getfixturevalue("platform_env")
    runtime, *_ = env
    await runtime.clients.update_client("platform-target", OAuth2ClientUpdate(require_consent=True))
    verifier = "p" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    rid, _, _ = await runtime.auth.start_authorization(
        client_id="platform-target",
        redirect_uri="https://b.example/cb",
        response_type="code",
        scope="openid profile",
        state="registration",
        nonce=None,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    if phase != "pending":
        approved = await runtime.auth.submit_consent(request_id=rid, user_id=7, tenant_id=9, decision="approve")
    await runtime.clients.create_client(
        OAuth2ClientCreate(client_id="keep-sequence", client_name="Other", redirect_uris=["https://other.example/cb"])
    )
    await runtime.clients.delete_client("platform-target")
    registered = await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="platform-target",
            client_name="New B",
            redirect_uris=["https://b.example/cb"],
            grant_types=["authorization_code", EXCHANGE_GRANT_TYPE],
            require_consent=True,
        )
    )
    if phase == "pending":
        with pytest.raises(OAuth2AuthorizationExpiredError):
            await runtime.auth.get_consent_details(rid)
        with pytest.raises(OAuth2AuthorizationExpiredError):
            await runtime.auth.submit_consent(request_id=rid, user_id=7, tenant_id=9, decision="approve")
        with runtime.auth._session_factory() as db:
            assert db.exec(select(OAuth2UserConsent)).all() == []
    elif phase == "code":
        from urllib.parse import parse_qs, urlsplit

        code = parse_qs(urlsplit(approved.redirect_uri).query)["code"][0]
        with pytest.raises(OAuth2InvalidGrantError):
            await runtime.auth.exchange_code(
                origin=ORIGIN,
                code=code,
                client_id="platform-target",
                client_secret=registered.client_secret,
                redirect_uri="https://b.example/cb",
                code_verifier=verifier,
            )
    with pytest.raises(OAuth2ConsentRequiredError):
        await exchange(env)


async def test_public_target_explicitly_enabled_accepts_first_party(request):
    env = request.getfixturevalue("platform_env")
    runtime, *_ = env
    await runtime.clients.create_client(
        OAuth2ClientCreate(
            client_id="public-target",
            client_name="Public B",
            client_type="public",
            redirect_uris=["https://public.example/cb"],
            grant_types=["authorization_code", EXCHANGE_GRANT_TYPE],
            require_consent=False,
        )
    )
    result = await runtime.platform_exchange.exchange(
        origin=ORIGIN, subject=env[5], audience="public-target", scope="openid"
    )
    assert result["scope"] == "openid"


async def test_exchanged_token_cannot_become_platform_subject(request):
    from fastapi.testclient import TestClient

    from bisheng.oauth2_provider.domain.schemas.platform_exchange import PLATFORM_SESSION_TOKEN_TYPE

    env = request.getfixturevalue("platform_env")
    result = await exchange(env)
    with TestClient(env[6], base_url=ORIGIN) as client:
        denied = client.post(
            "/api/v1/oauth2/token",
            data={
                "grant_type": EXCHANGE_GRANT_TYPE,
                "subject_token_type": PLATFORM_SESSION_TOKEN_TYPE,
                "subject_token": result["access_token"],
                "audience": "platform-target",
                "scope": "openid",
            },
        )
        assert denied.status_code == 400 and denied.json()["error"] == "invalid_grant"


async def test_parent_dependency_business_failure_returns_oauth_unavailable(request, monkeypatch):
    env = request.getfixturevalue("platform_env")
    runtime, *_ = env
    result = await exchange(env)

    async def unavailable_parent(reference):
        raise BaseErrorCode(code=24006, msg="private backend configuration failure")

    monkeypatch.setattr(runtime.platform_exchange, "_platform_validator", unavailable_parent)
    with pytest.raises(BaseErrorCode) as exc:
        await exchange(env)
    assert exc.value.code == 28117
    with pytest.raises(BaseErrorCode) as exc:
        await runtime.auth.userinfo("Bearer " + result["access_token"])
    assert exc.value.code == 28117
