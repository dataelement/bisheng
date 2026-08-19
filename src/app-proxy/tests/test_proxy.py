"""AC-21 / AC-25 / AC-33 / AC-36 — resolving the upstream and forwarding to it.

Two things are being pinned here that are easy to get subtly wrong:

* **The prefix contract (D5.2).** ``/apps/{slug}`` is stripped on the way in and
  re-announced as ``X-Forwarded-Prefix`` so the framework regenerates absolute
  URLs with it. Get this half-right and the app "works" until the first
  stylesheet — the failure is a blank white page, only on apps with static
  assets.
* **The switch window (D5.1/D4).** runtime-manager retires the old container
  after 30s; this cache holds an address for 3s. The inequality is the reason a
  version switch produces no 502s, so it is asserted rather than described.
"""

from __future__ import annotations

import json

from tests.conftest import NAVIGATE_HEADERS
from tests.fakes import DEFAULT_APP_ID, DEFAULT_UPSTREAM, EchoUpstream

SECOND_UPSTREAM = "http://172.20.0.9:8080"


def echo(response) -> dict:
    return json.loads(response.text)


def headers_of(record: dict) -> dict[str, str]:
    return {name.lower(): value for name, value in record["headers"]}


class TestRouteResolution:
    def test_route_cached_3s_and_invalidated_on_conn_error(
        self, logged_in, fake_manager, upstream_transport, frozen_clock
    ):
        """A refused connection means the address is stale — drop it, retry once.

        Without the invalidation the proxy would keep dialling a dead container
        for the rest of the TTL, turning a sub-second container replacement
        into three seconds of "应用恢复中" for everyone.
        """
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert len(fake_manager.calls) == 1, "second request must be served from the route cache"

        replacement = EchoUpstream()
        upstream_transport.register(SECOND_UPSTREAM, replacement)
        upstream_transport.refuse.add(DEFAULT_UPSTREAM)
        fake_manager.routes[DEFAULT_APP_ID] = {"upstream": SECOND_UPSTREAM, "version_id": "v2", "generation": 2}

        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert response.status_code == 200
        assert replacement.requests, "the retry must go to the freshly resolved address"
        assert len(fake_manager.calls) == 2, "exactly one re-fetch, not a retry loop"

    def test_second_failure_renders_recovering_not_a_502(self, logged_in, upstream_transport):
        upstream_transport.refuse.add(DEFAULT_UPSTREAM)
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200
        assert "恢复中" in response.text

    def test_upstream_is_bridge_ip_not_published_port(self, logged_in, upstream_transport):
        """AC-33: reachable only through here.

        The manager answers with the container's address on the ``bisheng-apps``
        bridge — host-reachable, externally unreachable, and identical in both
        deployment shapes. A ``127.0.0.1:<port>`` here would mean somebody
        published a port and every hosted app became directly dialable, bypassing
        every check in this package.
        """
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert upstream_transport.attempts == [DEFAULT_UPSTREAM]
        assert "127.0.0.1" not in DEFAULT_UPSTREAM and "localhost" not in DEFAULT_UPSTREAM

    def test_entry_stable_across_version_switch(
        self, logged_in, fake_manager, upstream_transport, echo_upstream, frozen_clock
    ):
        """AC-21 / AC-25: same URL before, during and after a release.

        During the switch window the cached (old) address is still served by the
        still-running old container — that is what the 30s grace is for — and
        after the TTL the same URL lands on the new one. No 502 at any point.
        """
        assert logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).status_code == 200

        replacement = EchoUpstream()
        upstream_transport.register(SECOND_UPSTREAM, replacement)
        fake_manager.routes[DEFAULT_APP_ID] = {"upstream": SECOND_UPSTREAM, "version_id": "v2", "generation": 2}

        assert logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).status_code == 200
        assert len(echo_upstream.requests) == 2, "inside the TTL the old container still serves"
        assert replacement.requests == []

        frozen_clock.advance(3.1)
        assert logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).status_code == 200
        assert len(replacement.requests) == 1


class TestPrefixStripping:
    def test_prefix_stripped_three_forms(self, logged_in, echo_upstream):
        """``/apps/foo``, ``/apps/foo/`` and ``/apps/foo/x?y=1`` (D5.2)."""
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)
        logged_in.get("/apps/foo/x?y=1", headers=NAVIGATE_HEADERS)

        paths = [(record["path"], record["query"]) for record in echo_upstream.requests]
        assert paths == [("/", ""), ("/", ""), ("/x", "y=1")]
        for record in echo_upstream.requests:
            assert headers_of(record)["x-forwarded-prefix"] == "/apps/foo"

    def test_relative_paths_work_through_entry(self, logged_in, echo_upstream):
        """A stylesheet the app emitted as ``/static/app.css`` resolves here."""
        response = logged_in.get("/apps/foo/static/app.css", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200
        assert echo_upstream.requests[-1]["path"] == "/static/app.css"

    def test_query_string_survives_untouched(self, logged_in, echo_upstream):
        logged_in.get("/apps/foo/search?q=%E4%B8%AD%E6%96%87&page=2", headers=NAVIGATE_HEADERS)
        assert echo_upstream.requests[-1]["query"] == "q=%E4%B8%AD%E6%96%87&page=2"


class TestForwarding:
    def test_method_body_and_response_are_passed_through(self, logged_in, echo_upstream):
        response = logged_in.post("/apps/foo/submit", json={"answer": "42"}, headers=NAVIGATE_HEADERS)

        assert response.status_code == 200
        record = echo(response)
        assert record["method"] == "POST"
        assert json.loads(record["body"]) == {"answer": "42"}

    def test_upstream_status_and_headers_reach_the_client(self, logged_in, echo_upstream):
        echo_upstream.status_code = 418
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 418
        assert response.headers["content-type"].startswith("application/json")

    def test_every_set_cookie_survives_the_hop(self, logged_in, echo_upstream):
        """Session + CSRF in one response is the ordinary case, not a corner one.

        Django, Rails, Flask-WTF and every "log in then set a CSRF token" flow
        emit two ``Set-Cookie`` headers at once. Building the response from a
        Mapping keeps the last one only, and the visitor sees "cannot log in" or
        "form POST 403" with a completely clean log on both sides — the app did
        send both cookies, and the proxy did return 200.
        """
        echo_upstream.response_headers = [
            (b"set-cookie", b"sessionid=abc; Path=/; HttpOnly"),
            (b"set-cookie", b"csrftoken=xyz; Path=/"),
        ]
        response = logged_in.get("/apps/foo/login", headers=NAVIGATE_HEADERS)

        cookies = response.headers.get_list("set-cookie")
        assert len(cookies) == 2, f"a cookie was dropped on the way back: {cookies}"
        assert any("sessionid=abc" in value for value in cookies)
        assert any("csrftoken=xyz" in value for value in cookies)

    def test_repeated_response_header_is_not_collapsed(self, logged_in, echo_upstream):
        """``Set-Cookie`` is the expensive case, but the rule is general."""
        echo_upstream.response_headers = [(b"vary", b"Accept"), (b"vary", b"Cookie")]
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert response.headers.get_list("vary") == ["Accept", "Cookie"]

    def test_response_hop_by_hop_headers_are_not_replayed(self, logged_in, echo_upstream):
        """They describe the upstream hop; replaying them desyncs this one."""
        echo_upstream.response_headers = [
            (b"connection", b"keep-alive"),
            (b"transfer-encoding", b"chunked"),
            (b"set-cookie", b"sessionid=abc; Path=/"),
        ]
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert "keep-alive" not in response.headers.get("connection", "").lower()
        assert response.headers.get_list("set-cookie") == ["sessionid=abc; Path=/"]

    def test_streaming_and_large_body_passthrough(self, logged_in, echo_upstream):
        """Hosted apps stream (SSE, downloads). Buffering would break both."""
        echo_upstream.stream_chunks = [b"x" * 1024] * 64
        with logged_in.stream("GET", "/apps/foo/download", headers=NAVIGATE_HEADERS) as response:
            assert response.status_code == 200
            received = sum(len(chunk) for chunk in response.iter_bytes())
        assert received == 64 * 1024

    def test_large_request_body_passthrough(self, logged_in, echo_upstream):
        payload = "y" * (256 * 1024)
        logged_in.post("/apps/foo/upload", content=payload.encode(), headers=NAVIGATE_HEADERS)
        assert len(echo_upstream.requests[-1]["body"]) == len(payload)

    def test_forged_header_has_no_effect_on_upstream_end_to_end(self, logged_in, echo_upstream):
        """AC-32 through the whole stack, not just the header helper.

        The underscore spelling is the CVE-2025-64484 shape: ASGI keeps it
        distinct, but a Django/Flask app behind us folds it onto the same key it
        reads identity from.
        """
        logged_in.get(
            "/apps/foo",
            headers={
                **NAVIGATE_HEADERS,
                "X_BiSheng_User_Id": "1",
                "x-bisheng-user-name": "root",
                "X-BISHENG-SUBJECT-KIND": "service_account",
                "X-Forwarded-Host": "attacker.example.com",
            },
        )
        received = headers_of(echo_upstream.requests[-1])

        assert received["x-bisheng-user-id"] == "42"
        assert received["x-bisheng-subject-kind"] == "human"
        assert received["x-forwarded-host"] != "attacker.example.com"

    def test_identity_headers_reach_the_app(self, logged_in, echo_upstream):
        """AC-31: the app can render "当前访问者：张三 · 研发中心"."""
        from urllib.parse import unquote

        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        received = headers_of(echo_upstream.requests[-1])

        assert unquote(received["x-bisheng-user-name"]) == "张三"
        assert unquote(received["x-bisheng-dept-name"]) == "研发中心"
        assert received["x-bisheng-dept-id"] == "BS@d4f1"
        assert received["x-bisheng-access-token"] == "obo.jwt.token"
        assert received["x-bisheng-request-id"]

    def test_platform_session_cookie_does_not_reach_the_app(self, logged_in, echo_upstream):
        """The container gets the 900s OBO token, not a full platform session."""
        logged_in.cookies.set("theme", "dark")
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        cookie = headers_of(echo_upstream.requests[-1]).get("cookie", "")

        assert "access_token_cookie" not in cookie
        assert "theme=dark" in cookie


# ---- bare app root gets a trailing slash --------------------------------
#
# `/apps/foo` and `/apps/foo/` reach the same page but are different bases for
# relative URLs. A bundle that emits `./assets/index-x.js` — the normal way to be
# prefix-agnostic, and what the skill pack sanctions — resolves it against
# `/apps/` under the slash-less URL and asks for `/apps/assets/index-x.js`, i.e.
# another slug. Every asset 404s and the user sees a white page with nothing in
# the server log to explain it. Found on 114 with a real Vite app (steel-diorama).


class TestTrailingSlashRedirect:
    def test_bare_root_redirects_with_slash(self, logged_in) -> None:
        response = logged_in.get("/apps/foo", follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == "/apps/foo/"

    def test_query_survives_the_redirect(self, logged_in) -> None:
        response = logged_in.get("/apps/foo?a=1&b=2", follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == "/apps/foo/?a=1&b=2"

    def test_slashed_root_is_served_not_redirected(self, logged_in) -> None:
        # The whole point is to land here; bouncing again would be a loop.
        response = logged_in.get("/apps/foo/", follow_redirects=False)
        assert response.status_code != 308

    def test_deep_path_is_never_redirected(self, logged_in) -> None:
        response = logged_in.get("/apps/foo/assets/index-x.js", follow_redirects=False)
        assert response.status_code != 308

    def test_non_get_is_not_redirected(self, logged_in) -> None:
        # An API POST to the app root resolves no relative URLs; redirecting it
        # would only cost a hop.
        response = logged_in.post("/apps/foo", follow_redirects=False)
        assert response.status_code != 308
