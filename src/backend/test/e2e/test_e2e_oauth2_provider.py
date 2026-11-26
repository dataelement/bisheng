"""Real HTTP E2E for F026; no application imports, DB access or mocked transports.

Run serially after deployment. See feature e2e-checklist.md for environment and
isolated pytest invocation. Tokens/secrets must never be committed or logged.
OAuth clients are platform-global; only dedicated e2e-oauth115- clients change.
The externally provisioned ordinary user must belong to E2E_TEST_TENANT_ID.
"""

import base64
import hashlib
import os
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token

PREFIX = "e2e-oauth115-"
CLIENTS = f"{API_BASE.rstrip('/')}/oauth2/clients"
OAUTH = f"{API_BASE.rstrip('/')}/oauth2"
ORIGIN = API_BASE.rstrip("/").removesuffix("/api/v1")
REDIRECT = "http://127.0.0.1:39115/e2e-oauth115-callback"
SCOPES = "openid profile email offline_access"
pytestmark = pytest.mark.asyncio


def oauth_json(response, status=200, error=None):
    """OAuth wire contract, deliberately distinct from platform envelopes."""
    assert response.status_code == status
    body = response.json()
    assert isinstance(body, dict)
    assert not {"status_code", "status_message", "data"} & body.keys()
    if error:
        assert body["error"] == error
        assert "access_token" not in body
    assert "no-store" in response.headers.get("cache-control", "")
    return body


class OAuthStory:
    """Feature-only HTTP operations and fail-closed client cleanup."""

    def __init__(self, client, admin, user, tenant):
        self.http = client
        self.admin = auth_headers(admin)
        self.user = auth_headers(user)
        self.tenant = tenant

    async def envelope(self, method, url, **kwargs):
        response = await self.http.request(method, url, headers=self.admin, **kwargs)
        assert {"status_code", "status_message", "data"} <= response.json().keys()
        return assert_resp_200(response)

    async def rows(self):
        rows = []
        page = 1
        while True:
            data = await self.envelope("GET", CLIENTS, params={"page": page, "page_size": 200})
            rows.extend(data["data"])
            if len(rows) >= data["total"]:
                return rows
            assert data["data"], "Incomplete OAuth client pagination"
            page += 1
            assert page <= 100, "Refuse incomplete client enumeration"

    async def cleanup(self):
        # The generic helper uses name/id; OAuth requires client_name/client_id.
        rows = await self.rows()
        untouched = {r["client_id"]: r for r in rows if not r["client_id"].startswith(PREFIX)}
        for row in rows:
            if not row["client_id"].startswith(PREFIX):
                continue
            assert row["client_name"].startswith(PREFIX) and row["is_builtin"] is False
            cid = row["client_id"]
            detail = await self.envelope("GET", f"{CLIENTS}/{cid}")
            assert detail["client_id"] == cid
            assert detail["client_name"].startswith(PREFIX) and detail["is_builtin"] is False
            await self.envelope("DELETE", f"{CLIENTS}/{cid}")
            assert_resp_error(await self.http.get(f"{CLIENTS}/{cid}", headers=self.admin), 28102)
        after = await self.rows()
        assert not any(r["client_id"].startswith(PREFIX) for r in after)
        assert {r["client_id"]: r for r in after if r["client_id"] in untouched} == untouched

    async def create(self, kind="public", **overrides):
        cid = f"{PREFIX}{kind}-{secrets.token_hex(5)}"
        payload = {
            "client_id": cid,
            "client_name": cid,
            "client_type": kind,
            "redirect_uris": [REDIRECT],
            "allowed_scopes": SCOPES.split(),
            "grant_types": ["authorization_code", "refresh_token"],
            "require_pkce": True,
            "require_consent": True,
        }
        payload.update(overrides)
        created = await self.envelope("POST", CLIENTS, json=payload)
        detail = await self.envelope("GET", f"{CLIENTS}/{cid}")
        assert detail == created["client"]
        assert "client_secret" not in detail and "client_secret_hash" not in detail
        assert detail["has_secret"] == (kind == "confidential")
        assert bool(created.get("client_secret")) == (kind == "confidential")
        return created

    def authorization(self, registration):
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params = {
            "client_id": registration["client"]["client_id"],
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": SCOPES,
            "state": secrets.token_urlsafe(18),
            "nonce": secrets.token_urlsafe(18),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return verifier, params

    async def code(self, registration, decision="approve"):
        verifier, params = self.authorization(registration)
        response = await self.http.get(f"{OAUTH}/authorize", params=params, headers=self.user)
        assert response.status_code == 302
        location = urlsplit(response.headers["location"])
        assert location.path == "/oauth-consent"
        request_id = parse_qs(location.query)["request_id"][0]
        url = f"{OAUTH}/consent/{request_id}"
        details = assert_resp_200(await self.http.get(url, headers=self.user))
        assert details["client_id"] == params["client_id"]
        assert details["state"] == params["state"] and details["redirect_uri"] == REDIRECT
        assert set(details["scopes"]) == set(SCOPES.split())
        assert details["expires_in"] > 0
        response = await self.http.post(url, headers=self.user, json={"decision": decision})
        assert {"status_code", "status_message", "data"} <= response.json().keys()
        callback = assert_resp_200(response)["redirect_uri"]
        parts = urlsplit(callback)
        assert (parts.scheme, parts.netloc, parts.path) == ("http", "127.0.0.1:39115", "/e2e-oauth115-callback")
        query = parse_qs(parts.query)
        assert query["state"] == [params["state"]]
        assert_resp_error(await self.http.get(url, headers=self.user), 28108)
        if decision == "deny":
            assert query["error"] == ["access_denied"] and "code" not in query
            return None
        return {
            "grant_type": "authorization_code",
            "client_id": params["client_id"],
            "redirect_uri": REDIRECT,
            "code": query["code"][0],
            "code_verifier": verifier,
        }, params

    async def exchange(self, registration):
        form, params = await self.code(registration)
        if registration.get("client_secret"):
            form["client_secret"] = registration["client_secret"]
        response = await self.http.post(f"{OAUTH}/token", data=form)
        tokens = oauth_json(response)
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] > 0
        assert set(tokens["scope"].split()) == set(SCOPES.split())
        assert tokens["refresh_token"] and tokens["id_token"]
        oauth_json(await self.http.post(f"{OAUTH}/token", data=form), 400, "invalid_grant")
        return tokens, params

    async def userinfo(self, access):
        return await self.http.get(f"{OAUTH}/userinfo", headers={"Authorization": f"Bearer {access}"})

    async def refresh(self, registration, token):
        form = {"grant_type": "refresh_token", "client_id": registration["client"]["client_id"], "refresh_token": token}
        if registration.get("client_secret"):
            form["client_secret"] = registration["client_secret"]
        return await self.http.post(f"{OAUTH}/token", data=form)


@pytest.fixture
async def story():
    # Require credentials before even setup cleanup can write remotely.
    user = os.environ.get("E2E_USER_TOKEN", "").strip()
    tenant = os.environ.get("E2E_TEST_TENANT_ID", "").strip()
    if not user or not tenant:
        pytest.skip("Supply E2E_USER_TOKEN and E2E_TEST_TENANT_ID for the dedicated ordinary user")
    assert not os.environ.get("PYTEST_XDIST_WORKER"), "Run this prefix-owned suite serially"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        admin = await get_admin_token(client)
        assert admin != user, "Admin and ordinary user must be distinct"
        ctx = OAuthStory(client, admin, user, tenant)
        denied = await client.get(CLIENTS, headers=ctx.user)
        assert denied.status_code == 200
        assert_resp_error(denied, 403)
        try:
            await ctx.cleanup()
            yield ctx
        finally:
            await ctx.cleanup()


class TestE2EOAuth2Provider:
    @pytest.mark.parametrize("kind", ["public", "confidential"])
    async def test_ac01_management_permission_pairs(self, story, kind):
        """AC-01, AC-10: admin CRUD/rotation; ordinary user denied every management operation."""
        registration = await story.create(kind)
        cid = registration["client"]["client_id"]
        url = f"{CLIENTS}/{cid}"
        denied_create = {
            "client_id": f"{PREFIX}denied",
            "client_name": f"{PREFIX}denied",
            "redirect_uris": [REDIRECT],
            "client_type": kind,
        }
        for method, target, body in [
            ("GET", CLIENTS, None),
            ("GET", url, None),
            ("POST", CLIENTS, denied_create),
            ("PUT", url, {"enabled": False}),
            ("POST", f"{url}/rotate-secret", None),
            ("DELETE", url, None),
        ]:
            response = await story.http.request(method, target, headers=story.user, **({"json": body} if body else {}))
            # Platform HTTPException handler returns HTTP 200 with business 403;
            # its legacy error envelope omits optional data (main.py).
            assert response.status_code == 200
            envelope = assert_resp_error(response, 403)
            assert envelope["status_message"] == "Super admin permission required"
            assert (await story.envelope("GET", url))["enabled"] is True
        assert not any(r["client_id"] == denied_create["client_id"] for r in await story.rows())
        for enabled in (False, True):
            await story.envelope("PUT", url, json={"enabled": enabled, "description": "E2E updated"})
            detail = await story.envelope("GET", url)
            assert detail["enabled"] is enabled and detail["description"] == "E2E updated"
            if not enabled:
                _, params = story.authorization(registration)
                oauth_json(await story.http.get(f"{OAUTH}/authorize", params=params), 401, "invalid_client")
        if kind == "confidential":
            rotated = await story.envelope("POST", f"{url}/rotate-secret")
            assert rotated["client_secret"] != registration["client_secret"]
            assert "client_secret" not in await story.envelope("GET", url)
            form, _ = await story.code(registration)
            form["client_secret"] = registration["client_secret"]
            oauth_json(await story.http.post(f"{OAUTH}/token", data=form), 401, "invalid_client")
            form["client_secret"] = rotated["client_secret"]
            tokens = oauth_json(await story.http.post(f"{OAUTH}/token", data=form))
            oauth_json(await story.userinfo(tokens["access_token"]))
        assert any(r["client_id"] == cid for r in await story.rows())
        await story.envelope("DELETE", url)
        assert_resp_error(await story.http.get(url, headers=story.admin), 28102)

    @pytest.mark.parametrize("kind", ["public", "confidential"])
    async def test_ac02_to_ac08_oidc_lifecycle(self, story, kind):
        """AC-02-AC-08: S256 consent/code, JWKS verification, userinfo, refresh replay/family revoke."""
        registration = await story.create(kind)
        tokens, params = await story.exchange(registration)
        info = oauth_json(await story.userinfo(tokens["access_token"]))
        assert info["tenant_id"] == story.tenant
        assert info["sub"] and info["preferred_username"] and info["name"] and info["tenant_name"]
        metadata_response = await story.http.get(f"{ORIGIN}/.well-known/openid-configuration")
        assert metadata_response.status_code == 200
        metadata = metadata_response.json()
        assert not {"status_code", "data"} & metadata.keys()
        issuer = os.environ.get("E2E_OAUTH_ISSUER", ORIGIN).rstrip("/")
        assert metadata["issuer"] == issuer
        for key, path in {
            "authorization_endpoint": "authorize",
            "token_endpoint": "token",
            "userinfo_endpoint": "userinfo",
            "revocation_endpoint": "revoke",
            "jwks_uri": "jwks",
        }.items():
            assert metadata[key] == f"{issuer}/api/v1/oauth2/{path}"
        assert metadata["code_challenge_methods_supported"] == ["S256"]
        assert "ES256" in metadata["id_token_signing_alg_values_supported"]
        jwks = oauth_json(await story.http.get(f"{OAUTH}/jwks"))
        assert jwks["keys"] and all("d" not in k for k in jwks["keys"])
        for field in ("id_token", "access_token"):
            header = jwt.get_unverified_header(tokens[field])
            assert header["alg"] == "ES256"
            key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
            claims = jwt.decode(
                tokens[field],
                jwt.PyJWK.from_dict(key).key,
                algorithms=["ES256"],
                audience=params["client_id"],
                issuer=issuer,
                leeway=min(120, max(0, int(os.environ.get("E2E_JWT_LEEWAY_SECONDS", "0")))),
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            assert claims["sub"] == info["sub"] and claims["tenant_id"] == story.tenant
            if field == "id_token":
                assert claims["nonce"] == params["nonce"]
        rotated = oauth_json(await story.refresh(registration, tokens["refresh_token"]))
        assert rotated["refresh_token"] != tokens["refresh_token"]
        assert oauth_json(await story.userinfo(rotated["access_token"]))["sub"] == info["sub"]
        oauth_json(await story.refresh(registration, tokens["refresh_token"]), 400, "invalid_grant")
        oauth_json(await story.refresh(registration, rotated["refresh_token"]), 400, "invalid_grant")
        oauth_json(await story.userinfo(rotated["access_token"]), 401, "invalid_token")
        # A fresh family proves explicit RFC7009 revocation separately from replay.
        fresh, _ = await story.exchange(registration)
        form = {"token": fresh["refresh_token"], "client_id": params["client_id"]}
        if registration.get("client_secret"):
            form["client_secret"] = registration["client_secret"]
        for token in (fresh["refresh_token"], fresh["refresh_token"], "e2e-oauth115-unknown-token"):
            response = await story.http.post(f"{OAUTH}/revoke", data={**form, "token": token})
            assert response.status_code == 200 and response.content == b""
        oauth_json(await story.refresh(registration, fresh["refresh_token"]), 400, "invalid_grant")
        oauth_json(await story.userinfo(fresh["access_token"]), 401, "invalid_token")

    async def test_ac02_ac03_ac04_invalid_redirect_pkce_and_denial(self, story):
        """AC-02-AC-04: exact redirect, required/S256 PKCE, verifier mismatch and consent denial."""
        registration = await story.create()
        _, params = story.authorization(registration)
        for change in (
            {"redirect_uri": REDIRECT + "/wrong"},
            {"code_challenge": ""},
            {"code_challenge_method": "plain"},
        ):
            response = await story.http.get(f"{OAUTH}/authorize", params={**params, **change}, headers=story.user)
            oauth_json(response, 400, "invalid_request")
            assert "location" not in response.headers
        await story.code(registration, "deny")
        form, _ = await story.code(registration)
        form["code_verifier"] = "x" * 64
        oauth_json(await story.http.post(f"{OAUTH}/token", data=form), 400, "invalid_grant")
        oauth_json(await story.userinfo("e2e-oauth115-invalid"), 401, "invalid_token")

    async def test_ac09_builtin_client_read_only(self, story):
        """AC-09: seeded desktop public client remains intact (browser compatibility is manual)."""
        builtin = await story.envelope("GET", f"{CLIENTS}/dsh-desktop")
        assert builtin["is_builtin"] is True and builtin["client_type"] == "public"
        assert builtin["require_pkce"] is True and builtin["allow_loopback_port"] is True
        assert builtin["redirect_uris"] == ["http://127.0.0.1/dsh/callback"]
