"""AC-18..23: real TCP first-party cookie exchange, explicit consent and source logout."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest

from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientUpdate
from bisheng.oauth2_provider.domain.schemas.exchange import EXCHANGE_GRANT_TYPE
from bisheng.oauth2_provider.domain.schemas.platform_exchange import PLATFORM_SESSION_TOKEN_TYPE
from bisheng.user.api.endpoints.platform_auth import router as platform_auth_router
from test.e2e.helpers.local_provider import local_http_server
from test.oauth2_provider.test_platform_exchange import ORIGIN, oauth2_env, platform_env  # noqa: F401


@pytest.mark.usefixtures("platform_env")
async def test_platform_cookie_silent_consent_and_logout_over_tcp(request):
    """AC-18/19/20/21/22/23: no pair approval; user consent and session revocation enforced."""
    runtime, source, _, _, _, _, app = request.getfixturevalue("platform_env")
    app.include_router(platform_auth_router, prefix="/api/v1")
    web = await source.issue(7, 9, "bisheng-web")
    sid = web["session_id"]
    data = {
        "grant_type": EXCHANGE_GRANT_TYPE,
        "subject_token_type": PLATFORM_SESSION_TOKEN_TYPE,
        "audience": "platform-target",
        "scope": "openid profile",
    }
    csrf = {"Origin": ORIGIN, "X-CSRF-Token": web["csrf_token"]}
    with local_http_server(app) as base_url:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"Host": "bisheng.example.com", "X-Forwarded-Proto": "https"},
            trust_env=False,
            timeout=10,
            follow_redirects=False,
        ) as client:
            client.cookies.set("platform_session_hint", sid)
            client.cookies.set("platform_access_" + sid, web["access_token"])
            rejected = await client.post("/api/v1/oauth2/token", data=data)
            assert rejected.status_code == 400 and rejected.json()["error"] == "invalid_request"
            minted = await client.post("/api/v1/oauth2/token", data=data, headers=csrf)
            assert minted.status_code == 200, minted.text
            token = minted.json()["access_token"]
            jwks = (await client.get("/api/v1/oauth2/jwks")).json()
            key = jwt.PyJWK.from_dict(jwks["keys"][0]).key
            claims = jwt.decode(token, key, algorithms=["ES256"], issuer=ORIGIN, audience="platform-target")
            assert (claims["sub"], claims["tenant_id"]) == ("7", "9")
            with pytest.raises(jwt.InvalidAudienceError):
                jwt.decode(token, key, algorithms=["ES256"], audience="different-target")
            await runtime.clients.update_client("platform-target", OAuth2ClientUpdate(require_consent=True))
            denied = await client.post("/api/v1/oauth2/token", data=data, headers=csrf)
            assert denied.status_code == 400 and denied.json()["error"] == "consent_required"
            authorization = await client.get(
                "/api/v1/oauth2/authorize",
                params={
                    "client_id": "platform-target",
                    "redirect_uri": "https://b.example/cb",
                    "response_type": "code",
                    "scope": "openid profile",
                    "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(b"e2e-platform-verifier" * 3).digest())
                    .decode()
                    .rstrip("="),
                    "code_challenge_method": "S256",
                    "state": "e2e-platform-exchange",
                },
            )
            assert authorization.status_code == 302, authorization.text
            rid = parse_qs(urlsplit(authorization.headers["location"]).query)["request_id"][0]
            approved = await client.post("/api/v1/oauth2/consent/" + rid, json={"decision": "approve"}, headers=csrf)
            assert approved.status_code == 200 and approved.json()["status_code"] == 200
            minted = await client.post("/api/v1/oauth2/token", data=data, headers=csrf)
            assert minted.status_code == 200, minted.text
            token = minted.json()["access_token"]
            info = await client.get("/api/v1/oauth2/userinfo", headers={"Authorization": "Bearer " + token})
            assert info.status_code == 200 and info.json()["sub"] == "7"
            revoked = await client.delete("/api/v1/oauth2/consent/grants/platform-target", headers=csrf)
            assert revoked.status_code == 200 and revoked.json()["status_code"] == 200
            denied = await client.get("/api/v1/oauth2/userinfo", headers={"Authorization": "Bearer " + token})
            assert denied.status_code == 401 and denied.json()["error"] == "invalid_token"
            await runtime.clients.update_client("platform-target", OAuth2ClientUpdate(require_consent=False))
            minted = await client.post("/api/v1/oauth2/token", data=data, headers=csrf)
            assert minted.status_code == 200
            token = minted.json()["access_token"]
            logout = await client.post("/api/v1/auth/logout", json={}, headers=csrf)
            assert logout.status_code == 200 and logout.json()["status_code"] == 200
            denied = await client.get("/api/v1/oauth2/userinfo", headers={"Authorization": "Bearer " + token})
            assert denied.status_code == 401 and denied.json()["error"] == "invalid_token"
