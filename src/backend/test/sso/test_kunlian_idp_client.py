"""T031 覆盖 AC-02, AC-07, AC-13, AC-17, AC-25。离线 RS256 与 HTTP 契约。"""

import base64
import json
import time
from importlib import import_module
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianIdentityUnavailableError,
    KunlianLoginInvalidError,
    KunlianSessionExpiredError,
)
from bisheng.core.config.sso_sync import KunlianConf

BASE = "https://fixture.example"
PATHS = ("/.well-known/openid-configuration", "/oidc/jwks", "/oidc/introspect")


async def test_introspection_response_limit_stops_reading_and_closes_stream(harness):
    """AC-13, AC-25:内省响应不能在完成无界缓冲后才判断大小。"""
    client, _, _, token = harness
    identity = await client.verify_id_token(token(), expected_nonce="fixture-nonce")

    class LargeBody(httpx.AsyncByteStream):
        reads = 0
        closed = False

        async def __aiter__(self):
            for _ in range(8):
                self.reads += 1
                yield b"x" * (512 * 1024)

        async def aclose(self):
            self.closed = True

    stream = LargeBody()
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    async with client:
        with pytest.raises(KunlianDependencyUnavailableError):
            await client.introspect(SecretStr("synthetic-at"), expected=identity)
    assert stream.reads <= 3 and stream.closed


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def harness(signing_key):
    module = import_module("bisheng.sso_sync.domain.clients.kunlian")
    if not hasattr(module, "KunlianOidcClient"):
        pytest.fail("T032 OIDC verification client is not implemented", pytrace=False)
    now = int(time.time())
    claims = {
        "iss": BASE,
        "sub": "subject-1",
        "aud": "client+fixture",
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "nonce": "fixture-nonce",
        "sid": "sid-1",
        "auth_time": now - 10,
        "tenant_id": "tenant-1",
        "workspace_id": "ws-1",
    }
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update(kid="fixture-1", use="sig", alg="RS256")
    introspection = {
        "active": True,
        "client_id": "client+fixture",
        "sub": "subject-1",
        "scope": "openid profile",
        "sid": "sid-1",
        "tenant_id": "tenant-1",
        "workspace_id": "ws-1",
        "exp": now + 300,
        "iss": BASE,
        "token_type": "Bearer",
    }
    discovery = {"issuer": BASE, "jwks_uri": BASE + "/oidc/jwks", "introspection_endpoint": BASE + "/oidc/introspect"}
    requests = []
    state = {"claims": claims, "jwks": [jwk], "introspection": introspection, "discovery": discovery, "failure": None}

    def respond(request):
        requests.append(request)
        if state["failure"]:
            raise httpx.ReadTimeout("fixture upstream secret must not leak", request=request)
        if request.url.path == PATHS[0]:
            return httpx.Response(200, json=state["discovery"])
        if request.url.path == PATHS[1]:
            return httpx.Response(200, json={"keys": state["jwks"]})
        assert request.url.path == PATHS[2]
        assert request.method == "POST"
        assert parse_qs(request.content.decode()) == {"token": ["opaque+AT"]}
        basic = base64.b64decode(request.headers["authorization"].split()[1]).decode()
        assert basic == "client%2Bfixture:fixture%2Bsecret"
        assert not any(name in request.headers for name in ("cookie", "x-api-key", "origin"))
        return httpx.Response(200, json=state["introspection"], headers={"set-cookie": "forbidden=1"})

    conf = KunlianConf(
        issuer=BASE,
        client_id="client+fixture",
        allowed_tenant_id="tenant-1",
        allowed_workspace_ids=["ws-1"],
        endpoint_allowlist=[BASE + p for p in PATHS],
    )
    client = module.KunlianOidcClient(
        conf, client_secret=SecretStr("fixture+secret"), transport=httpx.MockTransport(respond), clock=lambda: now
    )

    def token(**kwargs):
        values = dict(state["claims"])
        values.update(kwargs.pop("claims", {}))
        return SecretStr(
            jwt.encode(values, signing_key, algorithm="RS256", headers=kwargs.pop("headers", {"kid": "fixture-1"}))
        )

    return client, state, requests, token


async def test_valid_identity_and_each_introspection_has_no_allow_cache(harness):
    client, _, requests, token = harness
    async with client:
        identity = await client.verify_id_token(token(), expected_nonce="fixture-nonce")
        assert identity.subject == "subject-1" and identity.sid == "sid-1"
        for _ in range(2):
            active = await client.introspect(SecretStr("opaque+AT"), expected=identity)
            assert active.expires_at == identity.expires_at
    assert len([r for r in requests if r.url.path == PATHS[1]]) == 1
    assert len([r for r in requests if r.url.path == PATHS[2]]) == 2


@pytest.mark.parametrize(
    "patch",
    [
        {"iss": "https://attacker.example"},
        {"sub": ""},
        {"aud": "wrong-client"},
        {"aud": ["client+fixture", "other"]},
        {"azp": "other"},
        {"nonce": "wrong"},
        {"tenant_id": "other"},
        {"workspace_id": "other"},
        {"sid": ""},
        {"exp": 0},
        {"iat": True},
        {"nbf": 9999999999},
        {"auth_time": 9999999999},
    ],
)
async def test_id_token_claim_mismatches_reject(harness, patch):
    client, _, _, token = harness
    async with client:
        with pytest.raises(KunlianLoginInvalidError):
            await client.verify_id_token(token(claims=patch), expected_nonce="fixture-nonce")


async def test_unknown_kid_one_controlled_refresh_and_no_token_selected_urls(harness):
    client, state, requests, token = harness
    async with client:
        await client.verify_id_token(token(), expected_nonce="fixture-nonce")
        rotated = dict(state["jwks"][0], kid="rotated")
        state["jwks"] = [rotated]
        assert (
            await client.verify_id_token(token(headers={"kid": "rotated"}), expected_nonce="fixture-nonce")
        ).subject == "subject-1"
        for bad_header in (
            {"kid": "absent"},
            {"kid": "another-absent"},
            {"kid": "rotated", "jku": "https://attacker.example"},
        ):
            with pytest.raises(KunlianLoginInvalidError):
                await client.verify_id_token(token(headers=bad_header), expected_nonce="fixture-nonce")
    assert len([r for r in requests if r.url.path == PATHS[1]]) == 2
    assert all(str(r.url).startswith(BASE) for r in requests)


@pytest.mark.parametrize(
    "patch,error",
    [
        ({"active": False}, KunlianSessionExpiredError),
        ({"active": "true"}, KunlianIdentityUnavailableError),
        ({"sub": "other"}, KunlianIdentityUnavailableError),
        ({"client_id": "other"}, KunlianIdentityUnavailableError),
        ({"iss": "other"}, KunlianIdentityUnavailableError),
        ({"tenant_id": "other"}, KunlianIdentityUnavailableError),
        ({"sid": "other"}, KunlianIdentityUnavailableError),
        ({"workspace_id": "other"}, KunlianIdentityUnavailableError),
        ({"exp": 0}, KunlianSessionExpiredError),
        ({"token_type": "mac"}, KunlianIdentityUnavailableError),
    ],
)
async def test_introspection_bound_to_frozen_identity(harness, patch, error):
    client, state, _, token = harness
    async with client:
        identity = await client.verify_id_token(token(), expected_nonce="fixture-nonce")
        state["introspection"].update(patch)
        with pytest.raises(error):
            await client.introspect(SecretStr("opaque+AT"), expected=identity)


async def test_network_failure_is_closed_and_does_not_retry_post(harness):
    client, state, requests, token = harness
    async with client:
        identity = await client.verify_id_token(token(), expected_nonce="fixture-nonce")
        state["failure"] = True
        with pytest.raises(KunlianDependencyUnavailableError) as caught:
            await client.introspect(SecretStr("opaque+AT"), expected=identity)
        assert "fixture upstream secret" not in str(caught.value)
    assert len([r for r in requests if r.url.path == PATHS[2]]) == 1


async def test_discovery_cannot_redirect_jwks_to_other_registration(harness):
    client, state, requests, token = harness
    state["discovery"]["jwks_uri"] = "https://attacker.example/jwks"
    async with client:
        with pytest.raises(KunlianLoginInvalidError):
            await client.verify_id_token(token(), expected_nonce="fixture-nonce")
    assert len(requests) == 1


@pytest.mark.parametrize("mutation", ["unsigned", "hmac", "signature", "required"])
async def test_crypto_and_required_claim_failures(harness, mutation):
    client, state, requests, token = harness
    if mutation == "hmac":
        raw = SecretStr(
            jwt.encode(
                state["claims"],
                "fixture-hmac-key-is-not-rsa-public-key",
                algorithm="HS256",
                headers={"kid": "fixture-1"},
            )
        )
    elif mutation == "unsigned":
        raw = SecretStr(jwt.encode(state["claims"], None, algorithm="none", headers={"kid": "fixture-1"}))
    elif mutation == "signature":
        parts = token().get_secret_value().split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        raw = SecretStr(".".join(parts))
    else:
        del state["claims"]["auth_time"]
        raw = token()
    async with client:
        with pytest.raises(KunlianLoginInvalidError):
            await client.verify_id_token(raw, expected_nonce="fixture-nonce")
    if mutation in ("hmac", "unsigned"):
        assert not requests


async def test_multi_audience_requires_matching_authorized_party(harness):
    client, _, _, token = harness
    async with client:
        identity = await client.verify_id_token(
            token(claims={"aud": ["client+fixture", "another"], "azp": "client+fixture"}),
            expected_nonce="fixture-nonce",
        )
        assert identity.client_id == "client+fixture"
