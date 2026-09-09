"""Opt-in live Nginx/Gateway/Python checks. No default host, account or credentials.

See F062 desktop-handoff-checklist.md for the isolated manifest and run command.
These tests do not automate a real desktop app, OS keychain or browser SSO.
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.e2e
PREFIX = "e2e-f062-"
ADMIN = "/api/v1/dsh/admin"


def require(condition: bool, message: str):
    """Keep credential-bearing values out of pytest assertion introspection."""
    __tracebackhide__ = True
    if not condition:
        pytest.fail(message, pytrace=False)


def raw(response: httpx.Response, *, status: int = 200) -> dict:
    __tracebackhide__ = True
    require(response.status_code == status, f"DSH HTTP status mismatch: expected {status}, got {response.status_code}")
    require(response.headers.get("content-type", "").startswith("application/json"), "DSH returned non-JSON content")
    require(bool(response.headers.get("x-request-id")), "DSH response lacks X-Request-ID")
    require("no-store" in response.headers.get("cache-control", ""), "DSH response lacks no-store")
    result = response.json()
    require(isinstance(result, dict) and "status_code" not in result, "DSH desktop response must be raw JSON")
    return result


def platform(response: httpx.Response) -> dict:
    __tracebackhide__ = True
    require(response.status_code == 200, f"Platform HTTP failure: {response.status_code}")
    body = response.json()
    require(isinstance(body, dict) and body.get("status_code") == 200, "Platform business request failed")
    require("status_message" in body and isinstance(body.get("data"), dict), "Incomplete platform success envelope")
    return body["data"]


def desktop_error(response: httpx.Response, status: int, code: str):
    __tracebackhide__ = True
    body = raw(response, status=status)
    require(body.get("error", {}).get("code") == code, f"Expected DSH error {code}")
    require(body.get("request_id") == response.headers.get("x-request-id"), "Error request ID mismatch")


@dataclass(repr=False)
class Actor:
    name: str
    user_id: str
    tenant_id: str
    token: str = field(repr=False)


@dataclass(repr=False)
class LiveDsh:
    base: str
    client: httpx.AsyncClient
    actors: dict[str, Actor] = field(repr=False)
    manifest: dict = field(repr=False)
    request_ids: list[str] = field(default_factory=list)

    async def request(self, method: str, path: str, *, actor: str | None = None, access: str | None = None, **kwargs):
        __tracebackhide__ = True
        require(path.startswith("/api/") and not path.startswith("//"), "Only same-origin API paths are allowed")
        headers = kwargs.pop("headers", {})
        if actor:
            headers.update(auth_headers(self.actors[actor].token))
        if access:
            headers["Authorization"] = f"Bearer {access}"
        self.client.cookies.clear()
        response = await self.client.request(method, path, headers=headers, **kwargs)
        request_id = response.headers.get("x-request-id", "")
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id) and len(self.request_ids) < 300:
            self.request_ids.append(request_id)
        return response

    async def seat(self) -> dict | None:
        user = self.actors["user"]
        for state in ("ASSIGNED", "REVOKED"):
            cursor = None
            for _ in range(10):
                data = platform(
                    await self.request(
                        "GET",
                        ADMIN + "/users",
                        actor="root",
                        params={
                            "tenant_id": user.tenant_id,
                            "keyword": user.name,
                            "seat_state": state,
                            "limit": 100,
                            **({"cursor": cursor} if cursor else {}),
                        },
                    )
                )
                for item in data["items"]:
                    if str(item["user_id"]) == user.user_id:
                        require(
                            str(item["tenant_id"]) == user.tenant_id,
                            "Test seat has a different tenant; refusing mutation",
                        )
                        require(
                            item.get("username") == user.name and user.name.startswith(PREFIX),
                            "Test seat name ownership mismatch",
                        )
                        return item
                if not data["has_more"]:
                    break
                cursor = data["next_cursor"]
                require(bool(cursor), "Missing management cursor")
            else:
                pytest.fail("Test seat lookup exceeded 1000 rows; refusing unbounded cleanup", pytrace=False)
        return None

    async def command(self, action: str, seat: dict) -> dict:
        __tracebackhide__ = True
        require(action in {"revoke", "reassign"}, "Unsupported test cleanup action")
        user = self.actors["user"]
        operation_id = str(uuid4())
        data = platform(
            await self.request(
                "POST",
                f"{ADMIN}/users/{user.user_id}/{action}",
                actor="root",
                params={"tenant_id": user.tenant_id},
                json={"operation_id": operation_id, "expected_grant_version": seat["grant_version"]},
            )
        )
        for _ in range(30):
            if data["status"] in {"SUCCEEDED", "FAILED"}:
                break
            await asyncio.sleep(1)
            data = platform(
                await self.request(
                    "GET", f"{ADMIN}/operations/{operation_id}", actor="root", params={"tenant_id": user.tenant_id}
                )
            )
        require(
            data["status"] == "SUCCEEDED",
            f"Dedicated test seat {action} did not succeed; retain operation ID {operation_id} for cleanup",
        )
        require(data["operation_id"] == operation_id, "Operation response ID mismatch")
        require(str(data["actor_user_id"]) == self.actors["root"].user_id, "Operation actor audit mismatch")
        observed = await self.seat()
        require(
            observed is not None and observed["state"] == ("REVOKED" if action == "revoke" else "ASSIGNED"),
            "GET did not confirm seat mutation",
        )
        return data

    async def cleanup(self):
        """Revoke only the manifest's verified dedicated user; never delete data."""
        seat = await self.seat()
        if seat and seat["state"] == "ASSIGNED":
            await self.command("revoke", seat)

    async def prepare_user(self):
        seat = await self.seat()
        if seat and seat["state"] == "REVOKED":
            await self.command("reassign", seat)

    async def authorization(self, *, decision: str = "approve") -> tuple[dict, dict, str]:
        __tracebackhide__ = True
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            callback = f"http://127.0.0.1:{listener.getsockname()[1]}/dsh/callback"
            transaction = raw(
                await self.request(
                    "POST",
                    "/api/dsh/authorizations",
                    json={
                        "client_id": "dsh-desktop",
                        "redirect_uri": callback,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                        "state": state,
                        "device_name": PREFIX + "http-harness",
                    },
                )
            )
            url = urlsplit(transaction["authorize_url"])
            require(
                f"{url.scheme}://{url.netloc}" == self.base and url.path == "/desktop-login",
                "Authorization URL escaped Nginx BASE",
            )
            require(parse_qs(url.query) == {"auth_id": [transaction["auth_id"]]}, "Authorization URL binding mismatch")
            require(0 < transaction["expires_in"] <= 300, "Invalid transaction lifetime")
            identity = platform(
                await self.request(
                    "POST",
                    "/api/v1/dsh/authorize",
                    actor="user",
                    headers={
                        "Origin": self.base,
                        "Sec-Fetch-Site": "same-origin",
                    },
                    json={"auth_id": transaction["auth_id"], "decision": decision},
                )
            )
            require(
                identity.get("redirect_uri") == callback and identity.get("state") == state,
                "Browser callback binding mismatch",
            )
            if decision == "approve":
                require(
                    bool(identity.get("identity_ticket")) and 0 < identity["expires_in"] <= 60,
                    "Invalid one-time ticket",
                )
            else:
                require(
                    identity.get("error") == "access_denied" and "identity_ticket" not in identity,
                    "Denial issued a ticket",
                )
            return transaction, identity, verifier

    async def login(self) -> dict:
        __tracebackhide__ = True
        transaction, identity, verifier = await self.authorization()
        data = raw(
            await self.request(
                "POST",
                "/api/dsh/token",
                json={
                    "grant_type": "identity_ticket",
                    "identity_ticket": identity["identity_ticket"],
                    "auth_id": transaction["auth_id"],
                    "code_verifier": verifier,
                },
            )
        )
        user = self.actors["user"]
        require(
            data.get("token_type") == "Bearer" and bool(data.get("access_token")) and bool(data.get("refresh_token")),
            "Incomplete DSH token response",
        )
        require(
            data["user"]["id"] == user.user_id and data["tenant"]["id"] == user.tenant_id, "Token identity mismatch"
        )
        return data


@pytest.fixture
async def live(request):
    __tracebackhide__ = True
    if os.environ.get("DSH_E2E_RUN") != "1":
        pytest.skip("Live DSH disabled: set DSH_E2E_RUN=1 only for an explicitly isolated HTTPS Nginx environment")
    if os.environ.get("DSH_E2E_ISOLATED_ENVIRONMENT") != "1":
        pytest.skip("Missing DSH_E2E_ISOLATED_ENVIRONMENT=1 attestation; no request sent")
    if hasattr(request.config, "workerinput"):
        pytest.skip("Live DSH uses one dedicated user; run without pytest-xdist")
    base = os.environ.get("DSH_E2E_BASE", "")
    manifest_path = os.environ.get("DSH_E2E_MANIFEST", "")
    if not base or not manifest_path:
        pytest.skip("Missing DSH_E2E_BASE or DSH_E2E_MANIFEST; no default host or credentials")
    url = urlsplit(base)
    require(
        url.scheme == "https"
        and bool(url.hostname)
        and not url.username
        and not url.password
        and url.path == ""
        and not url.query
        and not url.fragment,
        "DSH_E2E_BASE must be a credential-free HTTPS origin without trailing slash",
    )
    path = Path(manifest_path)
    require(path.is_file() and not path.is_symlink(), "Manifest must be an explicit regular file")
    require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, "Manifest must have mode 0600 or stricter")
    manifest = json.loads(path.read_text())
    require(
        manifest.get("environment") == "isolated" and manifest.get("base") == base, "Manifest isolation/BASE mismatch"
    )
    require(
        all(manifest.get(key) for key in ("backend_sha", "gateway_sha", "config_version")),
        "Record deployed revisions/config version before live testing",
    )
    require(
        "license_id" in manifest and isinstance(manifest.get("seat_limit"), int) and manifest["seat_limit"] > 0,
        "Manifest must pin the test license_id (null allowed) and seat_limit",
    )
    actors = {}
    for role in ("root", "t1_admin", "t2_admin", "user"):
        account = manifest.get("actors", {}).get(role, {})
        env_name = account.get("token_env", "")
        require(
            re.fullmatch(r"DSH_E2E_[A-Z0-9_]+_WEB_TOKEN", env_name) is not None,
            "Manifest must name dedicated web-token environment variables",
        )
        if not os.environ.get(env_name):
            pytest.skip(f"Missing dedicated credential {env_name}; no request sent")
        require(
            str(account.get("username", "")).startswith(PREFIX),
            "Every account, including Root, must have the e2e-f062- prefix",
        )
        require(
            all(re.fullmatch(r"[1-9][0-9]*", str(account.get(key, ""))) for key in ("user_id", "tenant_id")),
            "Manifest requires explicit positive user/tenant IDs",
        )
        actors[role] = Actor(
            account["username"], str(account["user_id"]), str(account["tenant_id"]), os.environ[env_name]
        )
    require(len({actor.user_id for actor in actors.values()}) == 4, "Four distinct dedicated identities are required")
    require(
        actors["user"].tenant_id == actors["t1_admin"].tenant_id != actors["t2_admin"].tenant_id,
        "T1/T2 identity scope mismatch",
    )
    tls = ssl.create_default_context(cafile=os.environ.get("DSH_E2E_CA_FILE"))
    async with httpx.AsyncClient(
        base_url=base, verify=tls, trust_env=False, follow_redirects=False, timeout=60
    ) as client:
        harness = LiveDsh(base, client, actors, manifest)
        for role, actor in actors.items():
            identity = platform(await harness.request("GET", "/api/v1/user/info", actor=role))
            require(
                str(identity.get("user_id")) == actor.user_id
                and identity.get("user_name") == actor.name
                and str(identity.get("tenant_id")) == actor.tenant_id,
                f"Verified identity mismatch for {role}; no seat mutation performed",
            )
            if role == "root":
                require(
                    identity.get("role") == "admin" or identity.get("is_global_super") is True,
                    "Dedicated Root role was not verified",
                )
            elif role.endswith("_admin"):
                require(
                    identity.get("is_child_admin") is True and identity.get("role") != "admin",
                    f"Dedicated tenant admin role was not verified: {role}",
                )
            else:
                require(
                    identity.get("role") != "admin"
                    and not identity.get("is_child_admin")
                    and not identity.get("is_department_admin"),
                    "Ordinary test identity has administrative privileges",
                )
        license_data = platform(await harness.request("GET", ADMIN + "/license", actor="root"))
        require(
            license_data.get("license_id") == manifest["license_id"]
            and license_data.get("seat_limit") == manifest["seat_limit"],
            "Live License differs from the pinned isolated manifest; no seat mutation performed",
        )
        try:
            yield harness
        finally:
            request.node.user_properties.append(("dsh_live_request_ids", json.dumps(harness.request_ids)))
            for key in ("backend_sha", "gateway_sha", "config_version"):
                request.node.user_properties.append((key, manifest[key]))


@pytest.fixture
async def seat_user(live):
    if os.environ.get("DSH_E2E_ALLOW_TEST_SEAT_MUTATION") != "1":
        pytest.skip("Missing DSH_E2E_ALLOW_TEST_SEAT_MUTATION=1; dedicated seat will not be changed")
    # Setup clears stale sessions from a prior interrupted run; teardown releases only this test seat.
    await live.cleanup()
    try:
        await live.prepare_user()
        yield live
    finally:
        await live.cleanup()


@pytest.fixture
async def model_user(live):
    if os.environ.get("DSH_E2E_ALLOW_MODEL_CALLS") != "1":
        pytest.skip("Real model calls disabled: DSH_E2E_ALLOW_MODEL_CALLS=1 required; no model/seat mutation performed")
    if not live.manifest.get("model_id"):
        pytest.skip("Manifest model_id missing; no provider request sent")
    if os.environ.get("DSH_E2E_ALLOW_TEST_SEAT_MUTATION") != "1":
        pytest.skip("Dedicated model session requires DSH_E2E_ALLOW_TEST_SEAT_MUTATION=1")
    await live.cleanup()
    try:
        await live.prepare_user()
        yield live
    finally:
        await live.cleanup()


async def test_ac32_config_and_normal_platform_identity(live):
    """AC-01/AC-32: single HTTPS Nginx discovery and existing Web identity remain usable."""
    config = raw(await live.request("GET", "/api/v1/dsh/config"))
    require(
        config == {"enabled": True, "client_id": "dsh-desktop", "contract_version": "0.4.0"},
        "Live environment is not enabled with frozen DSH contract",
    )


async def test_ac02_denial_and_wrong_origin(live):
    """AC-02/AC-03: explicit denial issues no ticket; cross-origin browser authorization is rejected."""
    before = await live.seat()
    transaction, _denial, _verifier = await live.authorization(decision="deny")
    response = await live.request(
        "POST",
        "/api/v1/dsh/authorize",
        actor="user",
        headers={"Origin": "https://invalid.example"},
        json={"auth_id": transaction["auth_id"]},
    )
    assert_resp_error(response, 403)
    after = await live.seat()
    require(
        (before or {}).get("grant_version") == (after or {}).get("grant_version"),
        "Denial changed the dedicated user's seat",
    )


async def test_ac25_three_roles_and_tenant_scope(live):
    """AC-25/AC-26/AC-30/AC-33: ordinary denied, tenant scoped, Root can explicitly inspect T1/T2."""
    assert_resp_error(await live.request("GET", ADMIN + "/license", actor="user"), 19801)
    for role in ("t1_admin", "t2_admin"):
        actor = live.actors[role]
        data = platform(await live.request("GET", ADMIN + "/users", actor=role, params={"limit": 1}))
        require(
            all(str(item["tenant_id"]) == actor.tenant_id for item in data["items"]),
            "Tenant page leaked another tenant",
        )
        platform(await live.request("GET", ADMIN + "/license", actor=role))
        platform(
            await live.request("GET", ADMIN + "/users", actor="root", params={"tenant_id": actor.tenant_id, "limit": 1})
        )
    assert_resp_error(
        await live.request(
            "GET", ADMIN + "/users", actor="t1_admin", params={"tenant_id": live.actors["t2_admin"].tenant_id}
        ),
        403,
    )


async def test_ac05_session_refresh_logout_revoke_reassign(seat_user):
    """AC-05/06/08/09/11/13/15/17/18/28/29: fixed seat and complete session lifecycle."""
    live = seat_user
    first = await live.login()
    first_seat = await live.seat()
    require(first_seat is not None and first_seat["state"] == "ASSIGNED", "First token did not yield an assigned seat")
    second = await live.login()
    require((await live.seat())["seat_id"] == first_seat["seat_id"], "Second device allocated another seat")
    models = raw(await live.request("GET", "/api/v1/dsh/models", access=second["access_token"]))
    require(models.get("object") == "list" and isinstance(models.get("data"), list), "Models contract mismatch")
    raw(await live.request("GET", "/api/v1/dsh/usage", access=second["access_token"]))
    refreshed = raw(
        await live.request(
            "POST", "/api/dsh/token", json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]}
        )
    )
    require(
        refreshed["refresh_token"] != first["refresh_token"] and refreshed["session_id"] == first["session_id"],
        "Refresh did not rotate within its session",
    )
    desktop_error(
        await live.request(
            "POST", "/api/dsh/token", json={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]}
        ),
        401,
        "refresh_token_reused",
    )
    desktop_error(
        await live.request("GET", "/api/v1/dsh/models", access=refreshed["access_token"]), 401, "session_revoked"
    )
    raw(await live.request("GET", "/api/v1/dsh/models", access=second["access_token"]))
    require(
        (await live.request("POST", "/api/dsh/logout", access=second["access_token"], json={})).status_code == 204,
        "Logout did not return 204",
    )
    require((await live.seat())["state"] == "ASSIGNED", "Logout released a fixed seat")
    await live.command("revoke", await live.seat())
    desktop_error(await live.request("GET", "/api/v1/dsh/models", access=second["access_token"]), 403, "seat_revoked")
    await live.command("reassign", await live.seat())
    desktop_error(await live.request("GET", "/api/v1/dsh/models", access=second["access_token"]), 403, "seat_revoked")
    await live.login()
    platform(await live.request("GET", "/api/v1/user/info", actor="user"))


async def test_ac03_pkce_failure_and_web_token_separation(seat_user):
    """AC-03/AC-16: wrong verifier cannot exchange; Web JWT cannot call DSH model APIs."""
    transaction, identity, _verifier = await seat_user.authorization()
    desktop_error(
        await seat_user.request(
            "POST",
            "/api/dsh/token",
            json={
                "grant_type": "identity_ticket",
                "identity_ticket": identity["identity_ticket"],
                "auth_id": transaction["auth_id"],
                "code_verifier": secrets.token_urlsafe(32),
            },
        ),
        400,
        "pkce_verification_failed",
    )
    desktop_error(
        await seat_user.request("GET", "/api/v1/dsh/models", access=seat_user.actors["user"].token),
        401,
        "invalid_access_token",
    )


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
async def test_ac19_optional_real_model_and_usage(model_user, stream):
    """AC-19/AC-20/AC-23: opt-in real provider JSON/SSE, terminal usage and post-call read."""
    live = model_user
    model_id = live.manifest["model_id"]
    credentials = await live.login()
    listed = raw(await live.request("GET", "/api/v1/dsh/models", access=credentials["access_token"]))
    require(
        any(item["id"] == model_id for item in listed["data"]), "Dedicated model is not in the authorized model list"
    )
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": stream,
        "max_tokens": 16,
    }
    headers = {"Authorization": "Bearer " + credentials["access_token"]}
    if not stream:
        body = raw(
            await live.request("POST", "/api/v1/dsh/chat/completions", access=credentials["access_token"], json=payload)
        )
        require(
            bool(body.get("choices")) and body.get("usage", {}).get("total_tokens", 0) > 0,
            "Real JSON response lacks output/usage",
        )
    else:
        payload["stream_options"] = {"include_usage": True}
        async with live.client.stream(
            "POST", "/api/v1/dsh/chat/completions", headers=headers, json=payload
        ) as response:
            require(
                response.status_code == 200
                and response.headers.get("content-type", "").startswith("text/event-stream"),
                "Real SSE response was not admitted",
            )
            done = False
            usage = False
            deadline = time.monotonic() + 90
            count = 0
            async for line in response.aiter_lines():
                count += 1
                require(
                    count <= 10000 and time.monotonic() <= deadline, "SSE exceeded bounded test duration/line count"
                )
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    done = True
                    break
                chunk = json.loads(value)
                require("error" not in chunk, "Real SSE returned an in-stream error")
                usage = usage or isinstance(chunk.get("usage"), dict)
            require(done and usage, "SSE did not supply usage and a successful DONE")
    raw(await live.request("GET", "/api/v1/dsh/usage", access=credentials["access_token"]))
