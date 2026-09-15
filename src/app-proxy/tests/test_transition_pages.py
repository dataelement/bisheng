"""AC-36 / AC-48 — the two transitional pages: 「发布中」 and 「应用恢复中」.

They differ from the four verdict pages in one property that the whole file
circles around: **they retry on their own**. A verdict ("no access", "stopped")
is settled, so its page is static; a transition is a window that closes by
itself, so its page reloads until the app answers and the visitor lands in it
without touching the keyboard.

Which of the two is shown is not a guess made from the failure mode. The
manager says so: a deploy in flight with nothing serving yet answers 409
``deploying`` (T083), and only a refused connection or a missing route is
"recovering". Guessing from a refused connection alone would show "publishing"
during a crash and "recovering" during a first publish — both wrong, both
unfixable from the page.
"""

from __future__ import annotations

import re

from tests.conftest import NAVIGATE_HEADERS, XHR_HEADERS
from tests.fakes import DEFAULT_APP_ID, DEFAULT_UPSTREAM, DEPLOYING_ROUTE, deny_response

_REFRESH = re.compile(r'<meta\s+http-equiv="refresh"\s+content="(\d+)"', re.IGNORECASE)


def _refresh_seconds(body: str) -> int | None:
    match = _REFRESH.search(body)
    return int(match.group(1)) if match else None


class TestDeploying:
    def test_deploying_page_on_generation_switch(self, logged_in, fake_manager):
        """AC-48 — the manager says a deploy is in flight → 「发布中」, not an error page."""
        fake_manager.routes[DEFAULT_APP_ID] = dict(DEPLOYING_ROUTE)

        response = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "发布中" in response.text
        assert "恢复中" not in response.text
        assert "问卷小助手" in response.text

    def test_deploying_answer_is_cached_like_a_route(self, logged_in, fake_manager):
        """A retrying page must not turn one deploy into a request storm on the manager."""
        fake_manager.routes[DEFAULT_APP_ID] = dict(DEPLOYING_ROUTE)
        for _ in range(3):
            logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)
        assert fake_manager.calls == [DEFAULT_APP_ID]


class TestRecovering:
    def test_recovering_page_on_upstream_unreachable(self, logged_in, upstream_transport):
        """AC-36 — a refused connection (after the one retry) is the crash window."""
        upstream_transport.refuse.add(DEFAULT_UPSTREAM)

        response = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)

        assert response.status_code == 200
        assert "恢复中" in response.text
        assert "发布中" not in response.text

    def test_recovering_page_when_manager_has_no_route(self, logged_in, fake_manager):
        fake_manager.routes[DEFAULT_APP_ID] = None
        assert "恢复中" in logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS).text


class TestAutoRetry:
    def test_auto_retry_markup_present(self, logged_in, fake_manager, upstream_transport):
        """Both pages carry a ``meta refresh`` **and** an inline reload timer.

        The meta tag is the no-JS floor; the script is what lets the interval
        back off instead of hammering a host that is still building.
        """
        fake_manager.routes[DEFAULT_APP_ID] = dict(DEPLOYING_ROUTE)
        deploying = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)

        fake_manager.routes[DEFAULT_APP_ID] = {"upstream": DEFAULT_UPSTREAM, "version_id": "v1", "generation": 1}
        fake_manager.calls.clear()
        upstream_transport.refuse.add(DEFAULT_UPSTREAM)
        recovering = logged_in.get("/apps/foo/", headers={**NAVIGATE_HEADERS, "Cookie": "access_token_cookie=b"})

        for response in (deploying, recovering):
            body = response.text
            seconds = _refresh_seconds(body)
            assert seconds is not None, "no <meta http-equiv=refresh>"
            assert 1 <= seconds <= 30
            assert "location.reload" in body
            assert "setTimeout" in body
            assert response.headers.get("Retry-After") is not None
            # Still self-contained: the page renders while the app is down.
            assert "http://" not in body.replace("http://www.w3.org", "")

    def test_ready_after_retry_enters_app(self, logged_in, fake_manager, upstream_transport, echo_upstream):
        """AC-48 — the reload the page issues is a plain navigation to the same
        URL, so the moment the route is live the next one enters the app."""
        fake_manager.script[DEFAULT_APP_ID] = [
            dict(DEPLOYING_ROUTE),
            {"upstream": DEFAULT_UPSTREAM, "version_id": "v2", "generation": 2},
        ]
        fake_manager.routes[DEFAULT_APP_ID] = {"upstream": DEFAULT_UPSTREAM, "version_id": "v2", "generation": 2}

        first = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)
        assert "发布中" in first.text
        assert not echo_upstream.requests

        # The route cache holds the "starting" answer for its TTL; the page's
        # retry interval is longer than that, so a reload always re-asks.
        from app_proxy import clients

        clients.get_manager_client().cache.clear()
        second = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)

        assert second.status_code == 200
        assert "发布中" not in second.text
        assert echo_upstream.requests, "the retry must land inside the app, not on another page"


class TestBoundaries:
    def test_mutually_exclusive_with_four_fallback_pages(self, logged_in, fake_backend, fake_manager):
        """A refused verdict never becomes a transition page — even while the
        manager would report the app as deploying. The verdict is decided first
        and the route is never consulted for a refusal (spec §3 ordering)."""
        fake_manager.routes[DEFAULT_APP_ID] = dict(DEPLOYING_ROUTE)
        for decision, marker in (
            ("forbidden", "无访问权限"),
            ("stopped", "已停用"),
            ("not_found", "不存在或未上线"),
            ("not_enabled", "未启用应用工场"),
        ):
            fake_backend.response = deny_response(decision)
            logged_in.cookies.set("access_token_cookie", f"session-{decision}")
            body = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS).text

            assert marker in body
            assert "发布中" not in body and "恢复中" not in body
            assert "http-equiv" not in body.lower(), f"{decision} must not auto-retry"
        assert fake_manager.calls == [], "no route lookup for a refused visit"

    def test_verdict_pages_never_carry_retry_markup(self, logged_in, fake_backend):
        fake_backend.response = deny_response("forbidden")
        body = logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS).text
        assert "location.reload" not in body

    def test_xhr_gets_json_not_transition_html(self, logged_in, fake_manager, upstream_transport):
        """Non-navigation callers get JSON + a real status for both windows (D7)."""
        fake_manager.routes[DEFAULT_APP_ID] = dict(DEPLOYING_ROUTE)
        deploying = logged_in.get("/apps/foo/api/data", headers=XHR_HEADERS)
        assert deploying.status_code == 503
        assert deploying.headers["content-type"].startswith("application/json")
        assert deploying.json()["decision"] == "deploying"
        assert deploying.json()["status_code"] == 16147
        assert deploying.headers.get("Retry-After") is not None

        fake_manager.routes[DEFAULT_APP_ID] = {"upstream": DEFAULT_UPSTREAM, "version_id": "v1", "generation": 1}
        from app_proxy import clients

        clients.get_manager_client().cache.clear()
        upstream_transport.refuse.add(DEFAULT_UPSTREAM)
        recovering = logged_in.get("/apps/foo/api/data", headers=XHR_HEADERS)
        assert recovering.status_code == 503
        assert recovering.json()["decision"] == "recovering"
        assert recovering.json()["status_code"] == 16148

    def test_ws_upgrade_during_deploy_gets_a_close_code(self, logged_in, fake_manager):
        """The third audience: a socket cannot read a page, so it gets 4503."""
        import pytest
        from starlette.websockets import WebSocketDisconnect

        fake_manager.routes[DEFAULT_APP_ID] = dict(DEPLOYING_ROUTE)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with logged_in.websocket_connect("/apps/foo/ws"):
                pass
        assert excinfo.value.code == 4503
