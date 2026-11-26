"""Independent access/session lifetimes and malformed callback rejection."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
import test_oauth2_provider as provider_tests
import test_protocol as protocol_tests

from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.common.errcode.oauth2_provider import OAuth2InvalidGrantError, OAuth2InvalidRedirectUriError
from bisheng.dsh.api.endpoints.local_auth import AuthorizationRequest
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository
from bisheng.oauth2_provider.domain.services.auth_service import _sha256_hex
from bisheng.oauth2_provider.domain.services.client_service import match_redirect_uri, validate_registered_redirect_uri

oauth2_env = provider_tests.oauth2_env
protocol_http_client = protocol_tests.protocol_http_client


@pytest.fixture
def clock(monkeypatch):
    import bisheng.oauth2_provider.domain.repositories.session as session_module
    import bisheng.oauth2_provider.domain.services.auth_service as auth_module

    class Clock(datetime):
        current = datetime(2030, 1, 1)

        @classmethod
        def utcnow(cls):
            return cls.current

        @classmethod
        def now(cls, tz=None):
            return cls.current.replace(tzinfo=UTC).astimezone(tz) if tz else cls.current

    monkeypatch.setattr(session_module, "datetime", Clock)
    monkeypatch.setattr(auth_module, "datetime", Clock)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    return Clock


async def short_refresh_tokens(runtime, monkeypatch, scope):
    original_create = runtime.clients.create_client

    async def create_short_refresh(body):
        return await original_create(body.model_copy(update={"access_token_ttl": 3600, "refresh_token_ttl": 300}))

    monkeypatch.setattr(runtime.clients, "create_client", create_short_refresh)
    return (await provider_tests._issue_security_tokens(runtime, scope=scope))[0]


@pytest.mark.parametrize("offline", [False, True])
async def test_access_session_survives_short_refresh_lifetime(oauth2_env, monkeypatch, clock, offline):
    runtime, _ = oauth2_env
    start = clock.current
    tokens = await short_refresh_tokens(runtime, monkeypatch, "openid offline_access" if offline else "openid")
    with runtime.auth._session_factory() as db:
        repo = OAuth2SessionRepository(db)
        assert repo.get_session(tokens.session_id).expires_at == start + timedelta(seconds=3600)
        if offline:
            assert repo.get_refresh_token(_sha256_hex(tokens.refresh_token)).expires_at == start + timedelta(
                seconds=300
            )
        else:
            assert tokens.refresh_token is None
    clock.current = start + timedelta(seconds=301)
    assert (await runtime.auth.userinfo(f"Bearer {tokens.access_token}")).sub == "42"
    if offline:
        with pytest.raises(OAuth2InvalidGrantError):
            await runtime.auth.refresh_access_token(
                origin="https://bisheng.example",
                refresh_token=tokens.refresh_token,
                client_id="security-client",
                client_secret=None,
            )


async def test_rotation_preserves_access_session_without_extending_refresh_token(oauth2_env, monkeypatch, clock):
    runtime, _ = oauth2_env
    start = clock.current
    tokens = await short_refresh_tokens(runtime, monkeypatch, "openid offline_access")
    clock.current = start + timedelta(seconds=120)
    refreshed = await runtime.auth.refresh_access_token(
        origin="https://bisheng.example",
        refresh_token=tokens.refresh_token,
        client_id="security-client",
        client_secret=None,
    )
    assert refreshed.refresh_expires_in == 300
    with runtime.auth._session_factory() as db:
        repo = OAuth2SessionRepository(db)
        assert repo.get_session(tokens.session_id).expires_at == start + timedelta(seconds=3720)
        assert repo.get_refresh_token(_sha256_hex(refreshed.refresh_token)).expires_at == start + timedelta(seconds=420)
    clock.current = start + timedelta(seconds=421)
    assert (await runtime.auth.userinfo(f"Bearer {refreshed.access_token}")).sub == "42"
    with pytest.raises(OAuth2InvalidGrantError):
        await runtime.auth.refresh_access_token(
            origin="https://bisheng.example",
            refresh_token=refreshed.refresh_token,
            client_id="security-client",
            client_secret=None,
        )


BAD_REDIRECTS = ["http://[::1/dsh/callback", "http://127.0.0.1:abc/dsh/callback", "http://127.0.0.1:65536/dsh/callback"]


@pytest.mark.parametrize("uri", BAD_REDIRECTS)
def test_malformed_redirect_registration_and_matching(uri):
    with pytest.raises(OAuth2InvalidRedirectUriError):
        validate_registered_redirect_uri(uri)
    assert not match_redirect_uri(uri, [uri], allow_loopback_port=True)
    assert not match_redirect_uri(uri, [uri], allow_loopback_port=False)
    assert not match_redirect_uri("http://127.0.0.1:45678/dsh/callback", [uri], allow_loopback_port=True)


@pytest.mark.parametrize("uri", BAD_REDIRECTS)
async def test_malformed_redirect_oauth_http_and_dsh_pair(oauth2_env, protocol_http_client, uri):
    runtime, redis = oauth2_env
    _, challenge = provider_tests._make_pkce()
    response = protocol_http_client.get(
        "/api/v1/oauth2/authorize",
        params={
            "client_id": "dsh-desktop",
            "redirect_uri": uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    dsh = DshAuthorizationService(redis, "https://bisheng.example", oauth2_clients=runtime.clients)
    with pytest.raises(DshInvalidRequestError):
        await dsh.create(
            AuthorizationRequest(
                client_id="dsh-desktop",
                redirect_uri=uri,
                code_challenge=challenge,
                code_challenge_method="S256",
                state="s" * 40,
            )
        )
