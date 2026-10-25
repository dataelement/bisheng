"""AC-31 / AC-32 — what reaches the hosted app, and what must never reach it.

The single most important file in this package. CVE-2025-64484 (oauth2-proxy,
CVSS 8.5) was an incomplete version of exactly this code: it stripped the
hyphenated spelling only, and an authenticated user could re-assert identity
with the underscore variant because WSGI-style frameworks fold both onto the
same key. What we host is uncontrolled Python that trusts ``X-BiSheng-*``
unconditionally, so "strip the ten names we know" is not a defence.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from app_proxy.headers import (
    INJECTED_HEADER_NAMES,
    build_injected_headers,
    encode_header_value,
    normalize_header_name,
    strip_platform_headers,
)
from tests.fakes import DEFAULT_HEADER_MATERIAL

#: Every spelling a client might use to smuggle an identity header in. The
#: middle four are the CVE: same header as far as the application is concerned.
FORGED_VARIANTS = [
    ("X-BiSheng-User-Id", "1"),
    ("X_BiSheng_User_Id", "1"),
    ("x-bisheng-user-id", "1"),
    ("X-BISHENG-USER-ID", "1"),
    ("x_bisheng_USER_name", "root"),
    ("X-BiSheng_Tenant-Id", "999"),
    ("x-bisheng-subject-kind", "service_account"),
    ("X_BISHENG_ACCESS_TOKEN", "forged.jwt"),
    ("x-BiSheng-Dept-Path", "/root"),
    ("X-Bisheng-Anything-New-We-Add-Later", "boom"),
]


def _names(pairs) -> set[str]:
    return {name.lower() for name, _ in pairs}


class TestNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("X-BiSheng-User-Id", "x-bisheng-user-id"),
            ("X_BiSheng_User_Id", "x-bisheng-user-id"),
            ("x_bisheng_user_id", "x-bisheng-user-id"),
            ("X-BISHENG-USER-ID", "x-bisheng-user-id"),
        ],
    )
    def test_underscore_hyphen_case_collapse_to_one_name(self, raw, expected):
        assert normalize_header_name(raw) == expected


class TestStrip:
    def test_strip_all_x_bisheng_equivalence_class(self):
        """AC-32: prefix match **after** normalisation, not a name allow-list.

        The last variant is a header name that does not exist today. It must
        still be dropped — otherwise every future injected header is a
        vulnerability until someone remembers to add it to a list.
        """
        kept = strip_platform_headers([*FORGED_VARIANTS, ("Accept", "text/html"), ("Cookie", "a=b")])
        for name, _ in FORGED_VARIANTS:
            assert normalize_header_name(name) not in _names(kept), f"{name} survived the strip"
        assert "accept" in _names(kept)

    def test_non_platform_headers_survive_untouched(self):
        """Over-stripping breaks real apps: only our namespace goes."""
        inbound = [
            ("Accept-Language", "zh-CN"),
            ("User-Agent", "Mozilla/5.0"),
            ("X-Requested-With", "XMLHttpRequest"),
            ("X-Custom-App-Header", "keep-me"),
            ("Authorization", "Bearer app-own-token"),
        ]
        kept = strip_platform_headers(inbound)
        assert _names(kept) == {name.lower() for name, _ in inbound}

    def test_forged_header_has_no_effect_on_upstream(self):
        """Forge + inject: the real visitor's values are the only ones left."""
        inbound = [("X_BiSheng_User_Id", "1"), ("x-bisheng-user-name", "root"), ("Accept", "*/*")]
        upstream = strip_platform_headers(inbound) + build_injected_headers(
            DEFAULT_HEADER_MATERIAL,
            slug="foo",
            request_id="req-1",
            obo_token="obo.jwt",
            proto="https",
            host="bisheng.example.com",
        )
        by_name = {}
        for name, value in upstream:
            by_name.setdefault(name.lower(), []).append(value)

        assert by_name["x-bisheng-user-id"] == ["42"], "forged value must not survive, and must not duplicate"
        assert unquote(by_name["x-bisheng-user-name"][0]) == "张三"

    def test_forwarded_headers_rewritten_not_passthrough(self):
        """D5.2: a hosted app that trusts Host builds its links from it."""
        inbound = [
            ("X-Forwarded-Prefix", "/evil"),
            ("X-Forwarded-Proto", "gopher"),
            ("X-Forwarded-Host", "attacker.example.com"),
            ("Forwarded", "host=attacker.example.com"),
        ]
        kept = strip_platform_headers(inbound)
        assert _names(kept) == set(), "client-supplied forwarding metadata must be dropped wholesale"

        injected = {
            name.lower(): value
            for name, value in build_injected_headers(
                DEFAULT_HEADER_MATERIAL,
                slug="foo",
                request_id="req-1",
                obo_token="obo.jwt",
                proto="https",
                host="bisheng.example.com",
            )
        }
        assert injected["x-forwarded-prefix"] == "/apps/foo"
        assert injected["x-forwarded-proto"] == "https"
        assert injected["x-forwarded-host"] == "bisheng.example.com"

    def test_hop_by_hop_and_framing_headers_dropped(self):
        """A proxy that forwards ``Transfer-Encoding`` desyncs the upstream parser."""
        inbound = [
            ("Connection", "keep-alive"),
            ("Keep-Alive", "timeout=5"),
            ("Transfer-Encoding", "chunked"),
            ("TE", "trailers"),
            ("Proxy-Authorization", "Basic x"),
            ("Upgrade", "websocket"),
            ("Host", "bisheng.example.com"),
            ("Content-Length", "12"),
        ]
        assert strip_platform_headers(inbound) == []

    def test_platform_session_cookie_removed_from_cookie_header(self):
        """The hosted app must get OBO, never a live platform session.

        Not in design §4.2 as written, but implied by AC-34's whole reason for
        existing: the browser sends ``access_token_cookie`` to ``/apps/*``
        because it is host-only and ``path=/`` (K7), so without this the
        container receives a credential that can impersonate the visitor
        against the entire platform API — strictly more power than the scoped,
        900s OBO token we hand it deliberately.
        """
        kept = dict(strip_platform_headers([("Cookie", "theme=dark; access_token_cookie=jwt.here; lang=zh")]))
        assert "access_token_cookie" not in kept["Cookie"]
        assert "theme=dark" in kept["Cookie"]
        assert "lang=zh" in kept["Cookie"]

    def test_cookie_header_dropped_when_only_platform_cookie(self):
        assert strip_platform_headers([("Cookie", "access_token_cookie=jwt.here")]) == []


class TestInject:
    def test_inject_ten_headers(self):
        """AC-31: all ten, including the subject kind the AC calls out."""
        injected = build_injected_headers(
            DEFAULT_HEADER_MATERIAL,
            slug="foo",
            request_id="req-42",
            obo_token="obo.jwt",
            proto="https",
            host="bisheng.example.com",
        )
        names = _names(injected)
        for expected in INJECTED_HEADER_NAMES:
            assert expected.lower() in names, f"missing injected header {expected}"
        assert len(INJECTED_HEADER_NAMES) == 10
        by_name = {name.lower(): value for name, value in injected}
        assert by_name["x-bisheng-subject-kind"] == "human"
        assert by_name["x-bisheng-request-id"] == "req-42"
        assert by_name["x-bisheng-access-token"] == "obo.jwt"
        assert by_name["x-bisheng-app-id"] == "app-0001"

    def test_request_id_is_ours_not_the_backends(self):
        """Correlation only works if one hop owns the id (D14 log contract)."""
        material = {**DEFAULT_HEADER_MATERIAL, "X-BiSheng-Request-Id": "stale-from-backend"}
        injected = {
            n.lower(): v
            for n, v in build_injected_headers(
                material, slug="foo", request_id="req-live", obo_token=None, proto="http", host="h"
            )
        }
        assert injected["x-bisheng-request-id"] == "req-live"

    def test_backend_cannot_inject_outside_our_namespace(self):
        """Defence in depth: the material dict is data, not a header allow-list."""
        material = {**DEFAULT_HEADER_MATERIAL, "Authorization": "Bearer platform", "X-Evil": "1"}
        names = _names(
            build_injected_headers(material, slug="foo", request_id="r", obo_token=None, proto="http", host="h")
        )
        assert "authorization" not in names
        assert "x-evil" not in names

    def test_missing_optional_material_is_omitted_not_empty(self):
        """An app checking ``if header:`` must not see a department that isn't there."""
        material = {"X-BiSheng-User-Id": "7", "X-BiSheng-Tenant-Id": "1", "X-BiSheng-Subject-Kind": "service_account"}
        names = _names(
            build_injected_headers(material, slug="foo", request_id="r", obo_token=None, proto="http", host="h")
        )
        assert "x-bisheng-dept-id" not in names
        assert "x-bisheng-access-token" not in names
        assert "x-bisheng-user-id" in names


class TestLatin1Safety:
    def test_percent_encoded_chinese_values_pass_latin1(self):
        """坑 9: HTTP headers are latin-1. A Chinese name goes in raw → h11 rejects it.

        Only reproduces on accounts with non-ASCII names, and test accounts are
        usually ``admin`` — which is why this is asserted mechanically here
        rather than left to the 114 walkthrough.
        """
        injected = build_injected_headers(
            DEFAULT_HEADER_MATERIAL,
            slug="foo",
            request_id="r",
            obo_token=None,
            proto="http",
            host="h",
        )
        for name, value in injected:
            name.encode("latin-1")
            value.encode("latin-1")  # would raise UnicodeEncodeError on raw 中文

        by_name = {n.lower(): v for n, v in injected}
        assert unquote(by_name["x-bisheng-user-name"]) == "张三"
        assert unquote(by_name["x-bisheng-dept-name"]) == "研发中心"
        assert unquote(by_name["x-bisheng-dept-path"]) == "毕昇科技/研发中心"

    def test_encoding_is_idempotent_for_already_encoded_material(self):
        """The backend may percent-encode too (T032). Double-encoding would
        show the user ``%E5%BC%A0`` in their own app — so ASCII in, ASCII out."""
        pre_encoded = "%E5%BC%A0%E4%B8%89"
        assert encode_header_value(pre_encoded) == pre_encoded
        assert unquote(encode_header_value(pre_encoded)) == "张三"

    def test_ascii_values_are_untouched(self):
        assert encode_header_value("BS@d4f1") == "BS@d4f1"
        assert encode_header_value("Zhang San") == "Zhang San"
