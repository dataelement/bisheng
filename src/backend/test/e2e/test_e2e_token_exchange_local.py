"""Real HTTP provider integration, isolated SQLite/FakeRedis; not a production deployment test."""

import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.oauth2_provider.api.endpoints.exchange import admin_router
from bisheng.oauth2_provider.api.endpoints.oidc import consent_router, public_router
from bisheng.oauth2_provider.api.router import well_known_router
from bisheng.oauth2_provider.domain.schemas.exchange import ACCESS_TOKEN_TYPE, EXCHANGE_GRANT_TYPE
from bisheng.oauth2_provider.runtime import get_oauth2_runtime
from test.e2e.helpers.local_provider import local_http_server
from test.oauth2_provider.test_exchange import ORIGIN, exchange_env, oauth2_env  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.usefixtures("exchange_env")
async def test_http_authorize_exchange_recipient_and_revocation(request):
    """AC-01/08/14/15/17: authorize A, exchange B, verify B and revoke source over TCP."""
    runtime, params, _, _ = request.getfixturevalue("exchange_env")
    # Async fixtures have already been resolved by pytest-asyncio in this request.
    app = FastAPI()
    for router in (public_router, consent_router, admin_router):
        app.include_router(router, prefix="/api/v1")
    app.include_router(well_known_router)
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=42, tenant_id=7, is_global_super=False
    )
    with local_http_server(app) as base_url:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"Host": "bisheng.example.com", "X-Forwarded-Proto": "https"},
            trust_env=False,
            timeout=10,
            follow_redirects=False,
        ) as client:
            meta = (await client.get("/.well-known/openid-configuration")).json()
            assert meta["issuer"] == ORIGIN and EXCHANGE_GRANT_TYPE in meta["grant_types_supported"]
            verifier = "b" * 64
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            auth = await client.get(
                "/api/v1/oauth2/authorize",
                params={
                    "client_id": "source-a",
                    "response_type": "code",
                    "redirect_uri": "https://a.example/cb",
                    "scope": "openid profile offline_access",
                    "state": "e2e-tokenexchange-local",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
            assert auth.status_code == 302
            pending = parse_qs(urlsplit(auth.headers["location"]).query)["request_id"][0]
            consent = await client.post(
                "/api/v1/oauth2/consent/" + pending, json={"decision": "approve"}, headers={"Origin": ORIGIN}
            )
            data = consent.json()
            assert data["status_code"] == 200
            code = parse_qs(urlsplit(data["data"]["redirect_uri"]).query)["code"][0]
            parent = await client.post(
                "/api/v1/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": "source-a",
                    "client_secret": params["client_secret"],
                    "redirect_uri": "https://a.example/cb",
                    "code": code,
                    "code_verifier": verifier,
                },
            )
            assert parent.status_code == 200
            parent_token = parent.json()["access_token"]
            exchanged = await client.post(
                "/api/v1/oauth2/token",
                auth=("source-a", params["client_secret"]),
                data={
                    "grant_type": EXCHANGE_GRANT_TYPE,
                    "subject_token": parent_token,
                    "subject_token_type": ACCESS_TOKEN_TYPE,
                    "audience": "target-b",
                    "scope": "openid profile",
                },
            )
            assert exchanged.status_code == 200, exchanged.text
            token = exchanged.json()["access_token"]
            jwks = (await client.get("/api/v1/oauth2/jwks")).json()
            key = jwt.PyJWK.from_dict(jwks["keys"][0]).key
            identity = jwt.decode(token, key, algorithms=["ES256"], issuer=ORIGIN, audience="target-b")
            assert identity["sub"] == "42" and identity["tenant_id"] == "7"
            with pytest.raises(jwt.InvalidAudienceError):
                jwt.decode(token, key, algorithms=["ES256"], audience="another-b")
            info = await client.get("/api/v1/oauth2/userinfo", headers={"Authorization": "Bearer " + token})
            assert info.status_code == 200 and info.json()["sub"] == "42"
            revoked = await client.post(
                "/api/v1/oauth2/revoke", auth=("source-a", params["client_secret"]), data={"token": parent_token}
            )
            assert revoked.status_code == 200
            denied = await client.get("/api/v1/oauth2/userinfo", headers={"Authorization": "Bearer " + token})
            assert denied.status_code == 401 and denied.json()["error"] == "invalid_token"
