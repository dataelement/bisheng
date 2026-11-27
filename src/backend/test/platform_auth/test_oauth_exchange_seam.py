"""Exchange boundaries backed by real platform sessions and temporary SQLite."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from starlette.requests import Request

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.application import oauth_exchange
from bisheng.user.domain.schemas.credential_reference import PLATFORM_REFERENCE_FIELDS
from test.platform_auth.test_platform_session import runtime as platform_runtime


@pytest.fixture
def runtime(tmp_path):
    service, clock, identity = platform_runtime.__wrapped__(tmp_path)
    clock[0] = datetime.now(UTC).replace(tzinfo=None)
    return service, clock, identity


def request(service, headers=None):
    app = SimpleNamespace(
        state=SimpleNamespace(
            platform_auth_service=service,
            platform_auth_settings=SimpleNamespace(public_origin="https://platform.test"),
        )
    )
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/oauth/token",
            "server": ("platform.test", 443),
            "client": ("127.0.0.1", 1),
            "app": app,
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        }
    )


def cookies(issued):
    sid = issued["session_id"]
    return f"platform_session_hint={sid}; platform_access_{sid}={issued['access_token']}"


def browser_headers(issued):
    return {
        "cookie": cookies(issued),
        "origin": "https://platform.test",
        "x-csrf-token": issued["csrf_token"],
        "sec-fetch-site": "same-origin",
    }


def signed(service, claims):
    return jwt.encode(
        claims,
        service.keys["access"],
        algorithm="HS256",
        headers={"typ": "bisheng-platform-access+jwt", "kid": "platform-access-v1"},
    )


@pytest.mark.parametrize("client", ["bisheng-web", "bisheng-mobile"])
@pytest.mark.parametrize("transport", ["body", "bearer", "cookie"])
async def test_subject_has_only_closed_verified_fields(runtime, client, transport):
    service, clock, _ = runtime
    issued = await service.issue(7, 9, client)
    claims = service.decode(issued["access_token"])
    clock[0] += timedelta(seconds=10)
    headers = browser_headers(issued) if transport == "cookie" else {}
    if transport == "bearer":
        headers["authorization"] = f"Bearer {issued['access_token']}"
    subject = await oauth_exchange.read_platform_exchange_subject(
        request(service, headers), issued["access_token"] if transport == "body" else None
    )
    assert set(subject) == {"user_id", "tenant_id", "client_id", "expires_at", "session_expires_at", "reference"}
    assert subject["user_id"] == 7 and type(subject["user_id"]) is int
    assert subject["tenant_id"] == 9 and type(subject["tenant_id"]) is int
    assert subject["client_id"] == client
    assert subject["expires_at"] == claims["exp"]
    assert subject["session_expires_at"] == int(datetime.fromisoformat(issued["session_expires_at"]).timestamp())
    assert subject["session_expires_at"] > subject["expires_at"]
    assert set(subject["reference"]) == PLATFORM_REFERENCE_FIELDS
    assert subject["reference"]["expires_at"] == datetime.fromtimestamp(claims["exp"], UTC).isoformat()
    assert issued["access_token"] not in str(subject)
    assert issued["csrf_token"] not in str(subject)


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "https://evil.test"},
        {"origin": ""},
        {"x-csrf-token": ""},
        {"x-csrf-token": "wrong"},
        {"sec-fetch-site": "cross-site"},
    ],
)
async def test_cookie_requires_origin_and_csrf_even_with_body(runtime, change):
    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-web")
    headers = browser_headers(issued) | change
    with pytest.raises(PlatformAuthError, match="csrf_rejected"):
        await oauth_exchange.read_platform_exchange_subject(request(service, headers), issued["access_token"])


@pytest.mark.parametrize(
    "headers",
    [
        {"cookie": "unrelated=1"},
        {"cookie": ""},
        {"origin": "https://evil.test"},
        {"origin": "null"},
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
    ],
)
async def test_explicit_token_cannot_bypass_browser_boundaries(runtime, headers):
    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    with pytest.raises(PlatformAuthError, match="csrf_rejected"):
        await oauth_exchange.read_platform_exchange_subject(request(service, headers), issued["access_token"])


@pytest.mark.parametrize("pair", ["cookie-bearer", "cookie-body", "bearer-body"])
async def test_conflicting_credentials_rejected(runtime, pair):
    service, _, _ = runtime
    first = await service.issue(7, 9, "bisheng-web")
    second = await service.issue(7, 9, "bisheng-mobile")
    headers = browser_headers(first) if pair.startswith("cookie") else {}
    if pair.endswith("bearer") or pair.startswith("bearer"):
        headers["authorization"] = f"Bearer {second['access_token']}"
    with pytest.raises(PlatformAuthError, match="credential_conflict"):
        await oauth_exchange.read_platform_exchange_subject(
            request(service, headers),
            first["access_token"]
            if pair.endswith("body") and pair != "cookie-body"
            else second["access_token"]
            if pair == "cookie-body"
            else None,
        )


@pytest.mark.parametrize("fixed_kind", ["legacy", "bootstrap"])
@pytest.mark.parametrize("transport", ["cookie", "body", "bearer"])
async def test_residual_fixed_cookie_does_not_hide_platform_subject(runtime, fixed_kind, transport):
    service, _, _ = runtime
    pending = await service.issue(7, 9, "bisheng-web", pending=True)
    issued = await service.bootstrap(pending["access_token"])
    fixed = pending["access_token"] if fixed_kind == "bootstrap" else "legacy-fixed-cookie"
    headers = browser_headers(issued)
    headers["cookie"] = (cookies(issued) + "; " if transport == "cookie" else "") + f"access_token_cookie={fixed}"
    if transport == "bearer":
        headers["authorization"] = f"Bearer {issued['access_token']}"
    subject = await oauth_exchange.read_platform_exchange_subject(
        request(service, headers), issued["access_token"] if transport == "body" else None
    )
    assert subject["reference"]["session_id"] == issued["session_id"]
    headers.pop("x-csrf-token")
    with pytest.raises(PlatformAuthError, match="csrf_rejected"):
        await oauth_exchange.read_platform_exchange_subject(
            request(service, headers), issued["access_token"] if transport == "body" else None
        )


@pytest.mark.parametrize("fixed_kind", ["legacy", "bootstrap"])
async def test_fixed_cookie_alone_is_never_a_subject(runtime, fixed_kind):
    service, _, _ = runtime
    pending = await service.issue(7, 9, "bisheng-web", pending=True)
    fixed = pending["access_token"] if fixed_kind == "bootstrap" else "legacy-fixed-cookie"
    headers = browser_headers(pending) | {"cookie": f"access_token_cookie={fixed}"}
    with pytest.raises(PlatformAuthError, match="invalid_access_token"):
        await oauth_exchange.read_platform_exchange_subject(request(service, headers))


async def test_matching_credentials_and_explicit_good_origin(runtime):
    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-web")
    headers = browser_headers(issued) | {"authorization": f"Bearer {issued['access_token']}"}
    await oauth_exchange.read_platform_exchange_subject(request(service, headers), issued["access_token"])
    await oauth_exchange.read_platform_exchange_subject(
        request(service, {"origin": "https://platform.test"}), issued["access_token"]
    )


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer ", "Digest abc"])
async def test_no_basic_or_empty_bearer(runtime, authorization):
    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    with pytest.raises(PlatformAuthError, match="invalid_auth_request"):
        await oauth_exchange.read_platform_exchange_subject(
            request(service, {"authorization": authorization}), issued["access_token"]
        )


@pytest.mark.parametrize(
    "kind", ["refresh", "legacy", "dsh", "signature", "bootstrap", "bound-bootstrap", "client", "tenant", "version"]
)
async def test_non_subject_credentials_rejected(runtime, kind):
    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    token = issued["access_token"]
    if kind == "refresh":
        token = issued["refresh_token"]
    elif kind in {"legacy", "dsh"}:
        token = jwt.encode({"user_id": 7, "tenant_id": 9, "kind": kind}, "legacy-test-key", algorithm="HS256")
    elif kind in {"bootstrap", "bound-bootstrap"}:
        pending = await service.issue(7, 9, "bisheng-web", pending=True)
        token = pending["access_token"]
        if kind == "bound-bootstrap":
            await service.bootstrap(token)
    else:
        claims = service.decode(token)
        if kind == "signature":
            token = jwt.encode(
                claims,
                "wrong-test-key",
                algorithm="HS256",
                headers={"typ": "bisheng-platform-access+jwt", "kid": "platform-access-v1"},
            )
        else:
            claims[{"client": "client_id", "tenant": "tenant_id", "version": "session_version"}[kind]] = {
                "client": "dsh",
                "tenant": "10",
                "version": 99,
            }[kind]
            token = signed(service, claims)
    with pytest.raises(PlatformAuthError):
        await oauth_exchange.read_platform_exchange_subject(request(service), token)


@pytest.mark.parametrize(
    "failure", ["access-expiry", "session-expiry", "logout", "token-version", "session-version", "parent"]
)
async def test_live_state_and_reference_validation(runtime, monkeypatch, failure):
    service, clock, identity = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    parent = issued
    if failure == "parent":
        ticket = await service.create_ticket(parent["access_token"], "https://platform.test")
        issued = await service.consume_ticket(ticket["ticket"], "https://platform.test")
    subject = await oauth_exchange.read_platform_exchange_subject(request(service), issued["access_token"])
    monkeypatch.setattr(oauth_exchange, "platform_auth_service", lambda: service)
    assert await oauth_exchange.validate_platform_exchange_reference(subject["reference"]) is None
    if failure == "access-expiry":
        clock[0] += timedelta(days=31)
    elif failure == "session-expiry":

        def expire(repo):
            row = repo.get(issued["session_id"])
            row.expires_at = clock[0] - timedelta(seconds=1)
            repo.add(row)

        await service.run(expire)
    elif failure in {"logout", "parent"}:
        await service.logout(parent["access_token"])
    elif failure == "token-version":
        identity["token_version"] += 1
    else:

        def bump(repo):
            row = repo.get(issued["session_id"])
            row.version += 1
            repo.add(row)

        await service.run(bump)
    with pytest.raises(PlatformAuthError):
        await oauth_exchange.read_platform_exchange_subject(request(service), issued["access_token"])
    with pytest.raises(PlatformAuthError):
        await oauth_exchange.validate_platform_exchange_reference(subject["reference"])


async def test_reference_remains_closed_and_errors_propagate(runtime, monkeypatch):
    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    subject = await oauth_exchange.read_platform_exchange_subject(request(service), issued["access_token"])
    monkeypatch.setattr(oauth_exchange, "platform_auth_service", lambda: service)
    with pytest.raises(PlatformAuthError):
        await oauth_exchange.validate_platform_exchange_reference(subject["reference"] | {"access_token": "forbidden"})
    error = PlatformAuthError("auth_service_unavailable")

    async def unavailable(token):
        raise error

    monkeypatch.setattr(service, "inspect", unavailable)
    with pytest.raises(PlatformAuthError) as caught:
        await oauth_exchange.read_platform_exchange_subject(request(service), issued["access_token"])
    assert caught.value is error
