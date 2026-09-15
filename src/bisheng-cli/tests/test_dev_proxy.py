"""T042 — the `bisheng dev` mini proxy: strip forged identity, inject the real one.

Mirrors `src/app-proxy/tests/test_headers.py` case for case, because the two
proxies must behave identically for an app to be testable locally (AC-23 /
AC-25). The forged-variant list is the CVE-2025-64484 shape: same header as far
as a WSGI-family framework is concerned, four spellings.
"""

from __future__ import annotations

import http.client
import io
import json
from urllib.parse import unquote

import httpx
import pytest

from bisheng_cli import devproxy
from bisheng_cli.devproxy import (
    HANDLE_TTL_SECONDS,
    INJECTED_HEADER_NAMES,
    DevIdentity,
    DevProxy,
    HandleMinter,
    build_injected_headers,
    build_upstream_headers,
    encode_header_value,
    normalize_header_name,
    strip_platform_headers,
)
from bisheng_cli.output import Emitter
from tests.helpers.platform_mock import FAKE_KEY

FORGED_VARIANTS = [
    ("X-BiSheng-User-Id", "1"),
    ("X_BiSheng_User_Id", "1"),
    ("x-bisheng-user-id", "1"),
    ("X-BISHENG-USER-ID", "1"),
    ("x_bisheng_USER_name", "root"),
    ("X-BiSheng_Tenant-Id", "999"),
    ("x-bisheng-subject-kind", "human"),
    ("X_BISHENG_ACCESS_TOKEN", "forged.jwt"),
    ("x-BiSheng-Dept-Path", "/root"),
    ("X-Bisheng-Anything-New-We-Add-Later", "boom"),
]

WHOAMI = {
    "actor_kind": "service_account",
    "actor_id": 123,
    "actor_name": "问卷小队开发号",
    "tenant_id": 1,
}


def _identity(**overrides) -> DevIdentity:
    return DevIdentity.from_whoami({**WHOAMI, **overrides}, app_id=overrides.pop("app_id", "app-1"))


def _names(pairs) -> set[str]:
    return {name.lower() for name, _ in pairs}


# ---- normalisation + strip (AC-25) -----------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("X-BiSheng-User-Id", "x-bisheng-user-id"),
        ("X_BiSheng_User_Id", "x-bisheng-user-id"),
        ("x_bisheng_user_id", "x-bisheng-user-id"),
        ("X-BISHENG-USER-ID", "x-bisheng-user-id"),
    ],
)
def test_underscore_hyphen_case_collapse_to_one_name(raw: str, expected: str) -> None:
    assert normalize_header_name(raw) == expected


def test_strip_all_x_bisheng_equivalence_class() -> None:
    kept = strip_platform_headers([*FORGED_VARIANTS, ("Accept", "*/*")])
    assert kept == [("Accept", "*/*")]


def test_non_platform_headers_survive_untouched() -> None:
    inbound = [("Accept", "text/html"), ("X-Custom-Thing", "kept"), ("Authorization", "Bearer app-own-token")]
    assert strip_platform_headers(inbound) == inbound


def test_forged_header_has_no_effect_on_upstream() -> None:
    identity = _identity()
    upstream = build_upstream_headers(FORGED_VARIANTS, identity, request_id="rid-1", handle="h")
    values = {name.lower(): value for name, value in upstream}
    assert values["x-bisheng-user-id"] == "123"
    assert unquote(values["x-bisheng-user-name"]) == "问卷小队开发号"
    assert values["x-bisheng-tenant-id"] == "1"
    assert values["x-bisheng-subject-kind"] == "service_account"
    assert values["x-bisheng-access-token"] == "h"
    assert "x-bisheng-dept-path" not in values
    assert "x-bisheng-anything-new-we-add-later" not in values
    # Every platform header on the wire is one of the canonical ten, exactly once.
    platform = [name for name, _ in upstream if name.lower().startswith("x-bisheng-")]
    assert len(platform) == len(set(platform))
    assert set(platform) <= set(INJECTED_HEADER_NAMES)


def test_forwarded_and_hop_by_hop_headers_dropped_and_rewritten() -> None:
    inbound = [
        ("X-Forwarded-Prefix", "/apps/evil"),
        ("X-Forwarded-Host", "attacker.example"),
        ("Forwarded", "for=1.2.3.4"),
        ("Transfer-Encoding", "chunked"),
        ("Connection", "keep-alive"),
        ("Host", "localhost:8080"),
        ("Content-Length", "99"),
    ]
    upstream = build_upstream_headers(inbound, _identity(), request_id="rid", handle=None, host="localhost:8080")
    values = dict(upstream)
    assert values["X-Forwarded-Prefix"] == ""  # dev = root path, same header the hosted proxy fills
    assert values["X-Forwarded-Proto"] == "http"
    assert values["X-Forwarded-Host"] == "localhost:8080"
    assert "forwarded" not in _names(upstream)
    assert not {"transfer-encoding", "connection", "host", "content-length"} & _names(upstream)


def test_platform_session_cookie_removed_but_app_cookies_kept() -> None:
    inbound = [("Cookie", "access_token_cookie=platform-jwt; theme=dark")]
    assert strip_platform_headers(inbound) == [("Cookie", "theme=dark")]
    assert strip_platform_headers([("Cookie", "access_token_cookie=platform-jwt")]) == []


# ---- inject (AC-23) ----------------------------------------------------------


def test_inject_headers_in_canonical_order_omitting_absent_material() -> None:
    injected = build_injected_headers(_identity(), request_id="rid-9", handle="handle-9", host="localhost")
    platform = [name for name, _ in injected if name.startswith("X-BiSheng-")]
    expected = [
        "X-BiSheng-User-Id",
        "X-BiSheng-User-Name",
        "X-BiSheng-Tenant-Id",
        "X-BiSheng-Subject-Kind",
        "X-BiSheng-App-Id",
        "X-BiSheng-Access-Token",
        "X-BiSheng-Request-Id",
    ]
    assert platform == expected  # same relative order as app-proxy's ten; Dept-* absent
    assert [name for name in INJECTED_HEADER_NAMES if name in platform] == platform
    values = dict(injected)
    assert values["X-BiSheng-App-Id"] == "app-1" and values["X-BiSheng-Request-Id"] == "rid-9"
    # Absent material is omitted, never emitted empty.
    assert "" not in [value for name, value in injected if name.startswith("X-BiSheng-")]


def test_no_app_ref_means_no_app_id_header() -> None:
    injected = dict(build_injected_headers(_identity(app_id=None), request_id="r", handle="h"))
    assert "X-BiSheng-App-Id" not in injected


def test_personal_token_holder_is_human_not_service_account() -> None:
    identity = _identity(actor_kind="natural_person")
    assert identity.subject_kind == "human"


def test_chinese_values_percent_encoded_once_ascii_untouched() -> None:
    assert encode_header_value("张三") == "%E5%BC%A0%E4%B8%89"
    assert encode_header_value("%E5%BC%A0%E4%B8%89") == "%E5%BC%A0%E4%B8%89"
    assert encode_header_value("plain-ascii") == "plain-ascii"
    assert "\r" not in encode_header_value("a\r\nb")
    name = dict(build_injected_headers(_identity(), request_id="r", handle=None))["X-BiSheng-User-Name"]
    assert name.isascii() and unquote(name) == "问卷小队开发号"


# ---- the short-lived handle ---------------------------------------------------


def test_handle_is_fresh_per_request_short_lived_and_never_the_key() -> None:
    now = [1_000_000.0]
    minter = HandleMinter(_identity(), now=lambda: now[0])
    first, second = minter.mint("rid-1"), minter.mint("rid-2")
    assert first != second
    assert FAKE_KEY not in first and "bs-sak-" not in first
    payload = minter.verify(first)
    assert payload and payload["rid"] == "rid-1"
    assert payload["exp"] - payload["iat"] == HANDLE_TTL_SECONDS == 900
    assert payload["sub"] == {"app_id": "app-1", "user_id": "123", "tenant_id": "1", "subject_kind": "service_account"}
    # Expired or tampered handles do not verify.
    now[0] += HANDLE_TTL_SECONDS + 1
    assert minter.verify(first) is None
    assert HandleMinter(_identity()).verify(first) is None  # another session's secret
    assert minter.verify(first[:-2] + "zz") is None


# ---- forwarding end to end ---------------------------------------------------


def _echo_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.dumps({"path": request.url.raw_path.decode(), "headers": request.headers.multi_items()})
        return httpx.Response(200, content=body, headers={"content-type": "application/json", "x-app": "yes"})

    return httpx.MockTransport(handler)


def test_forward_strips_and_injects_and_relays_response() -> None:
    seen: list[httpx.Request] = []
    identity = _identity()
    proxy = DevProxy(
        identity=identity,
        minter=HandleMinter(identity),
        app_port=1,
        listen_port=0,
        transport=_echo_transport(seen),
        request_id_factory=lambda: "fixed-rid",
    )
    result = proxy.forward("POST", "/submit?x=1", [*FORGED_VARIANTS, ("Content-Type", "text/plain")], b"hello")
    assert result.status == 200
    assert dict(result.headers)["x-app"] == "yes"
    assert b"".join(result.body)
    request = seen[0]
    assert request.method == "POST" and request.url.raw_path == b"/submit?x=1" and request.content == b"hello"
    assert request.headers["x-bisheng-user-id"] == "123"
    assert request.headers["x-bisheng-request-id"] == "fixed-rid"
    assert request.headers["x-bisheng-subject-kind"] == "service_account"
    assert proxy.minter.verify(request.headers["x-bisheng-access-token"])
    assert FAKE_KEY not in str(request.headers)
    proxy.stop()


def test_app_not_listening_is_a_readable_502_not_a_crash() -> None:
    identity = _identity()
    err = io.StringIO()
    proxy = DevProxy(
        identity=identity,
        minter=HandleMinter(identity),
        app_port=1,
        listen_port=0,
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))),
        emitter=Emitter(stdout=io.StringIO(), stderr=err),
    )
    result = proxy.forward("GET", "/", [], b"")
    assert result.status == 502
    assert "PORT" in b"".join(result.body).decode("utf-8")
    assert "警告" in err.getvalue()
    proxy.stop()


def test_real_listener_round_trip_over_loopback() -> None:
    """The stdlib server shell: bytes in on a socket, upstream over httpx, bytes out."""
    seen: list[httpx.Request] = []
    identity = _identity()
    proxy = DevProxy(
        identity=identity, minter=HandleMinter(identity), app_port=1, listen_port=0, transport=_echo_transport(seen)
    )
    proxy.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", proxy.listen_port, timeout=5)
        conn.request("GET", "/hello?a=b", headers={"X_BiSheng_User_Id": "forged", "X-Custom": "kept"})
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
    finally:
        proxy.stop()
    assert response.status == 200
    assert payload["path"] == "/hello?a=b"
    upstream = {name.lower(): value for name, value in payload["headers"]}
    assert upstream["x-bisheng-user-id"] == "123" and upstream["x-custom"] == "kept"
    assert proxy.url.startswith("http://127.0.0.1:")


def test_module_exposes_no_identity_override() -> None:
    # AC-25: nothing in the proxy takes "who to be" from anywhere but the identity
    # built from `whoami`.
    assert not [name for name in dir(devproxy) if "impersonat" in name.lower() or "on_behalf" in name.lower()]
