"""AC-25 / AC-35 — WebSocket reverse proxying and the three invariants (D6).

The upstream in these tests is a **real** WebSocket server on a loopback port
(:class:`tests.fakes.WsEchoUpstream`), reached through the proxy's real
``websockets`` client. Everything asserted about the handshake — which headers
the app saw, which path, which subprotocol — is therefore what a hosted app
would genuinely receive, exactly as the HTTP suite does with ``EchoUpstream``.

The three invariants, in the order the design numbers them:

① the connection's authorisation is fixed **at the handshake** —
  ``min(OBO remaining, ws_max_lifetime) + jitter`` — and the proxy hangs up
  with ``4001`` when it runs out;
② a revoke / stop / delete reaches open sockets **actively**: the backend
  posts to ``/internal/connections/close`` and the proxy closes them, with a
  periodic re-authorisation as the safety net for a node the push missed;
③ is a contract for the hosted app's frontend (re-handshake is normal), so
  the only thing to pin here is that the close codes it must handle are the
  ones documented.
"""

from __future__ import annotations

import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import BACKEND_SECRET
from tests.fakes import DEFAULT_APP_ID, DEFAULT_UPSTREAM, allow_response, deny_response, sign

WS_PATH = "/apps/foo/ws"


def _handshake(ws_upstream):
    assert ws_upstream.handshakes, "the upgrade never reached the app"
    return ws_upstream.handshakes[-1]


def _header_names(record) -> list[str]:
    return [name.lower().replace("_", "-") for name, _ in record["headers"]]


def _header(record, name: str) -> str | None:
    for key, value in record["headers"]:
        if key.lower() == name.lower():
            return value
    return None


def _wait_for_close(record, timeout: float = 3.0) -> int | None:
    """The upstream records its close code on its own thread; give it a moment."""
    deadline = time.monotonic() + timeout
    while record["close_code"] is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return record["close_code"]


class TestProxied:
    def test_allowed_upgrade_is_proxied_and_frames_echo_both_ways(self, logged_in, ws_upstream):
        with logged_in.websocket_connect(WS_PATH) as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "ping"
            ws.send_bytes(b"\x00\x01binary")
            assert ws.receive_bytes() == b"\x00\x01binary"
            ws.send_text(json.dumps({"n": 1}))
            assert json.loads(ws.receive_text()) == {"n": 1}
        assert _wait_for_close(_handshake(ws_upstream)) is not None, "client close must reach the app"

    def test_entry_prefix_stripped_and_query_kept(self, logged_in, ws_upstream):
        """D5.2 — the app sees ``/ws?room=1``, never ``/apps/foo/ws``."""
        with logged_in.websocket_connect("/apps/foo/ws?room=1&x=y"):
            pass
        assert _handshake(ws_upstream)["path"] == "/ws?room=1&x=y"

    def test_bare_root_upgrade_maps_to_slash(self, logged_in, ws_upstream):
        with logged_in.websocket_connect("/apps/foo"):
            pass
        assert _handshake(ws_upstream)["path"] == "/"

    def test_subprotocol_negotiated_end_to_end(self, logged_in, ws_upstream):
        """The client's offer reaches the app; the app's pick reaches the client."""
        with logged_in.websocket_connect(WS_PATH, subprotocols=["json", "chat"]) as ws:
            assert ws.accepted_subprotocol == "json"
        assert _handshake(ws_upstream)["subprotocol"] == "json"

    def test_client_close_code_reaches_upstream(self, logged_in, ws_upstream):
        with logged_in.websocket_connect(WS_PATH) as ws:
            ws.close(code=1000, reason="done")
        assert _wait_for_close(_handshake(ws_upstream)) == 1000

    def test_upstream_close_code_propagates_to_client(self, logged_in, ws_upstream):
        """An app that hangs up with its own code is heard verbatim by its frontend."""
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                ws.send_text("close:4000:app says bye")
                ws.receive_text()
        assert excinfo.value.code == 4000
        assert excinfo.value.reason == "app says bye"


class TestInvariantOneHeaders:
    """WS upgrades go through the *same* strip + inject as HTTP (AC-32)."""

    def test_forged_platform_headers_are_stripped_and_identity_injected(self, logged_in, ws_upstream):
        forged = {
            "X-BiSheng-User-Id": "1",
            "X_BiSheng_User_Id": "1",
            "x-bisheng-tenant-id": "999",
            "X-BiSheng-App-Id": "app-evil",
            "X-Forwarded-Host": "evil.example",
            "X-Forwarded-Prefix": "/evil",
        }
        with logged_in.websocket_connect(WS_PATH, headers=forged):
            pass

        record = _handshake(ws_upstream)
        assert _header(record, "X-BiSheng-User-Id") == "42"
        assert _header(record, "X-BiSheng-Tenant-Id") == "1"
        assert _header(record, "X-BiSheng-App-Id") == DEFAULT_APP_ID
        assert _header(record, "X-BiSheng-Access-Token") == "obo.jwt.token"
        assert _header(record, "X-BiSheng-Subject-Kind") == "human"
        assert _header(record, "X-BiSheng-Request-Id"), "the proxy mints the request id"
        assert _header(record, "X-Forwarded-Prefix") == "/apps/foo"
        assert _header(record, "X-Forwarded-Host") != "evil.example"
        # Exactly one of each platform header — the client's copies are gone.
        names = _header_names(record)
        assert names.count("x-bisheng-user-id") == 1
        assert names.count("x-bisheng-app-id") == 1
        assert "x-bisheng-user-name" in names, "percent-encoded Chinese name survives the handshake"
        assert _header(record, "X-BiSheng-User-Name") == "%E5%BC%A0%E4%B8%89"

    def test_platform_session_cookie_does_not_reach_the_app(self, logged_in, ws_upstream):
        logged_in.cookies.set("theme", "dark")
        with logged_in.websocket_connect(WS_PATH):
            pass
        cookie = _header(_handshake(ws_upstream), "Cookie") or ""
        assert "access_token_cookie" not in cookie
        assert "theme=dark" in cookie, "the app's own cookies must survive"

    def test_handshake_headers_are_not_duplicated(self, logged_in, ws_upstream):
        """``Sec-WebSocket-Key`` / ``-Version`` belong to the proxy's own
        handshake; replaying the browser's would break the upgrade."""
        with logged_in.websocket_connect(WS_PATH):
            pass
        names = _header_names(_handshake(ws_upstream))
        assert names.count("sec-websocket-key") == 1
        assert names.count("sec-websocket-version") == 1
        assert names.count("upgrade") == 1
        assert names.count("connection") == 1

    def test_forwarded_for_appends_the_peer(self, logged_in, ws_upstream):
        with logged_in.websocket_connect(WS_PATH, headers={"X-Forwarded-For": "203.0.113.9"}):
            pass
        assert (_header(_handshake(ws_upstream), "X-Forwarded-For") or "").startswith("203.0.113.9, ")


class TestRefusals:
    @pytest.mark.parametrize(
        ("decision", "close_code"),
        [("login", 4401), ("forbidden", 4403), ("stopped", 4403), ("not_found", 4404), ("not_enabled", 4503)],
    )
    def test_refused_verdicts_close_without_touching_the_app(
        self, proxy_client, fake_backend, fake_manager, ws_upstream, decision, close_code
    ):
        fake_backend.response = deny_response(decision)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with proxy_client.websocket_connect(WS_PATH):
                pass
        assert excinfo.value.code == close_code
        assert not ws_upstream.handshakes
        assert fake_manager.calls == []

    def test_upstream_unreachable_closes_4503_after_one_retry(self, logged_in, ws_transport, fake_manager):
        """D5.1 — a refused connection drops the cached route and re-asks once."""
        ws_transport.refuse.add(DEFAULT_UPSTREAM.replace("http://", "ws://"))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH):
                pass
        assert excinfo.value.code == 4503
        assert len(ws_transport.attempts) == 2
        assert fake_manager.calls == [DEFAULT_APP_ID, DEFAULT_APP_ID]

    def test_stale_route_is_refreshed_and_the_retry_connects(self, logged_in, ws_transport, fake_manager, ws_upstream):
        stale = "http://172.20.0.99:8080"
        ws_transport.refuse.add("ws://172.20.0.99:8080")
        fake_manager.script[DEFAULT_APP_ID] = [
            {"upstream": stale, "version_id": "v1", "generation": 1},
            {"upstream": DEFAULT_UPSTREAM, "version_id": "v2", "generation": 2},
        ]
        with logged_in.websocket_connect(WS_PATH) as ws:
            ws.send_text("hello")
            assert ws.receive_text() == "hello"
        assert ws_transport.attempts == ["ws://172.20.0.99:8080", DEFAULT_UPSTREAM.replace("http://", "ws://")]

    def test_no_live_instance_closes_4503(self, logged_in, fake_manager, ws_upstream):
        fake_manager.routes[DEFAULT_APP_ID] = None
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH):
                pass
        assert excinfo.value.code == 4503
        assert not ws_upstream.handshakes

    def test_upstream_rejects_handshake_closes_4503(self, logged_in, ws_upstream):
        """The app answered the upgrade with an HTTP error (no ``/ws`` route)."""
        ws_upstream.reject_status = 404
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH):
                pass
        assert excinfo.value.code == 4503


class TestInvariantOneLifetime:
    def test_lifetime_is_min_of_obo_and_max_plus_jitter(self):
        from app_proxy.websocket import connection_lifetime

        now = 1_000_000.0
        # OBO shorter than the cap → OBO wins.
        assert connection_lifetime(obo_expires_at=now + 900, now=now, max_lifetime=28800, jitter=0.0) == 900
        # Cap shorter than OBO → cap wins.
        assert connection_lifetime(obo_expires_at=now + 90000, now=now, max_lifetime=28800, jitter=0.0) == 28800
        # No OBO (secret unconfigured) → the cap alone.
        assert connection_lifetime(obo_expires_at=None, now=now, max_lifetime=28800, jitter=0.0) == 28800
        # Jitter is additive and bounded.
        value = connection_lifetime(obo_expires_at=now + 900, now=now, max_lifetime=28800, jitter=30.0)
        assert 900 <= value <= 930
        # An OBO already in the past is not a negative lifetime.
        assert connection_lifetime(obo_expires_at=now - 5, now=now, max_lifetime=28800, jitter=0.0) == 0

    def test_backend_supplied_expiry_beats_the_token_claim(self):
        """When the backend states ``obo_expires_at`` explicitly, it wins over
        decoding the token; the claim is the fallback for an older backend."""
        from app_proxy.websocket import obo_expiry

        assert obo_expiry({"obo_expires_at": 123456}, obo_token="not.a.jwt") == 123456
        # A JWT with exp=1700000000 in its payload, unsigned (only the claim is read).
        import base64

        payload = base64.urlsafe_b64encode(b'{"exp":1700000000}').rstrip(b"=").decode()
        assert obo_expiry({}, obo_token=f"h.{payload}.s") == 1700000000
        assert obo_expiry({}, obo_token=None) is None
        assert obo_expiry({}, obo_token="garbage") is None

    def test_expiry_closes_4001(self, logged_in, wired, ws_upstream):
        """The proxy, not the app, ends an expired connection — with 4001."""
        from app_proxy.config import set_config

        set_config(wired.with_overrides(ws_max_lifetime_seconds=0.3, ws_lifetime_jitter_seconds=0.0))
        started = time.monotonic()
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                ws.send_text("still here")
                assert ws.receive_text() == "still here"
                ws.receive_text()  # blocks until the proxy closes
        assert excinfo.value.code == 4001
        assert time.monotonic() - started < 3
        assert _wait_for_close(_handshake(ws_upstream)) == 4001, "the app is told the same code"

    def test_short_obo_bounds_the_lifetime(self, logged_in, fake_backend, ws_upstream):
        """A verdict whose OBO expires in 0.3 s yields a 0.3 s connection."""
        fake_backend.response = {**allow_response(), "obo_expires_at": time.time() + 0.3}
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                ws.receive_text()
        assert excinfo.value.code == 4001

    def test_backend_supplied_cap_beats_the_process_config(self, logged_in, fake_backend, ws_upstream):
        """``ws_max_lifetime_seconds`` in the verdict is the backend's config
        (``app_runtime.ws_max_lifetime_seconds``); the process env value is
        only the fallback for a backend that does not send it."""
        fake_backend.response = {**allow_response(), "ws_max_lifetime_seconds": 0.3}
        started = time.monotonic()
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                ws.receive_text()
        assert excinfo.value.code == 4001
        assert time.monotonic() - started < 3


def _sign_close(body: dict, secret: str = BACKEND_SECRET) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    return raw, {
        "X-Signature": sign("POST", "/internal/connections/close", raw, secret),
        "Content-Type": "application/json",
    }


class TestInvariantTwoRevocation:
    def test_close_endpoint_disconnects_the_users_sockets_with_the_reason_code(self, logged_in, ws_upstream):
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                ws.send_text("open")
                assert ws.receive_text() == "open"
                raw, headers = _sign_close({"app_id": DEFAULT_APP_ID, "user_ids": [42], "reason": "forbidden"})
                response = logged_in.post("/internal/connections/close", content=raw, headers=headers)
                assert response.status_code == 200
                assert response.json()["closed"] == 1
                ws.receive_text()
        assert excinfo.value.code == 4403
        assert _wait_for_close(_handshake(ws_upstream)) == 4403

    def test_close_endpoint_without_user_filter_closes_every_socket_of_the_app(self, logged_in, ws_upstream):
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                raw, headers = _sign_close({"app_id": DEFAULT_APP_ID, "reason": "stopped"})
                assert logged_in.post("/internal/connections/close", content=raw, headers=headers).json()["closed"] == 1
                ws.receive_text()
        assert excinfo.value.code == 4403

    def test_close_endpoint_ignores_other_users_and_apps(self, logged_in, ws_upstream):
        with logged_in.websocket_connect(WS_PATH) as ws:
            raw, headers = _sign_close({"app_id": DEFAULT_APP_ID, "user_ids": [7], "reason": "forbidden"})
            assert logged_in.post("/internal/connections/close", content=raw, headers=headers).json()["closed"] == 0
            raw, headers = _sign_close({"app_id": "app-other", "reason": "stopped"})
            assert logged_in.post("/internal/connections/close", content=raw, headers=headers).json()["closed"] == 0
            ws.send_text("still open")
            assert ws.receive_text() == "still open"

    def test_close_endpoint_requires_a_valid_signature(self, logged_in):
        raw, headers = _sign_close({"app_id": DEFAULT_APP_ID}, secret="wrong")
        assert logged_in.post("/internal/connections/close", content=raw, headers=headers).status_code == 401
        assert logged_in.post("/internal/connections/close", content=raw).status_code == 401

    def test_close_endpoint_fails_closed_without_a_secret(self, logged_in, wired):
        from app_proxy.config import set_config

        set_config(wired.with_overrides(backend_secret=""))
        raw, headers = _sign_close({"app_id": DEFAULT_APP_ID}, secret="")
        assert logged_in.post("/internal/connections/close", content=raw, headers=headers).status_code == 401

    @pytest.mark.parametrize(
        "raw",
        [b"not json", b"{}", b'{"app_id": ""}', b'{"app_id": "app-0001", "user_ids": "42"}'],
        ids=["not-json", "no-app-id", "empty-app-id", "user-ids-not-a-list"],
    )
    def test_close_endpoint_rejects_a_malformed_body_after_the_signature(self, logged_in, raw):
        """Signed but incoherent → 400; the signature is checked first, so an
        unsigned malformed body is still a 401 and reveals nothing."""
        headers = {"X-Signature": sign("POST", "/internal/connections/close", raw, BACKEND_SECRET)}
        assert logged_in.post("/internal/connections/close", content=raw, headers=headers).status_code == 400
        assert logged_in.post("/internal/connections/close", content=raw).status_code == 401

    def test_close_endpoint_unknown_reason_falls_back_to_4503(self, logged_in, ws_upstream):
        """A reason word the proxy does not know still ends the socket — with
        the "nothing answering, reconnect" code rather than a permission one."""
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                raw, headers = _sign_close({"app_id": DEFAULT_APP_ID, "reason": "some-new-word"})
                assert logged_in.post("/internal/connections/close", content=raw, headers=headers).json()["closed"] == 1
                ws.receive_text()
        assert excinfo.value.code == 4503

    def test_registry_forgets_a_closed_connection(self, logged_in):
        from app_proxy import connections

        with logged_in.websocket_connect(WS_PATH):
            assert connections.registry.count(DEFAULT_APP_ID) == 1
        deadline = time.monotonic() + 2
        while connections.registry.count(DEFAULT_APP_ID) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert connections.registry.count(DEFAULT_APP_ID) == 0

    def test_periodic_reauthorization_closes_when_the_verdict_flips(
        self, logged_in, wired, fake_backend, frozen_clock, ws_upstream
    ):
        """Safety net for a node the push never reached: the verdict is re-asked
        on an interval and a non-allow answer ends the connection."""
        from app_proxy.config import set_config

        set_config(wired.with_overrides(ws_reauthorize_interval_seconds=0.2))
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect(WS_PATH) as ws:
                ws.send_text("open")
                assert ws.receive_text() == "open"
                fake_backend.response = deny_response("forbidden")
                frozen_clock.advance(3.1)  # past the authz cache TTL
                ws.receive_text()
        assert excinfo.value.code == 4403
        assert len(fake_backend.calls) >= 2
