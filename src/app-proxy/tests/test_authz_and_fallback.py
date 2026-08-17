"""AC-26 / AC-28 / AC-29 / AC-30 / AC-12 — the verdict, its cache, and the four pages.

Two rules run through the whole file:

* **Fail closed.** Every way of not getting an answer (timeout, 5xx, an
  unparsable body, a decision string we have never heard of) ends in a refusal.
  A proxy that "carries on" when the permission engine is down is the one bug
  class that silently voids AC-12 for as long as nobody notices.
* **Pages, not errors.** A visitor who is refused sees a page that explains
  what to do next and offers the square — never a 404/502 shell. The status
  code split is deliberate: navigations get 200 + HTML (a QR-code scan must not
  land on a browser error page, design §7 步 7 spells out "不是 502 / 404"),
  programmatic requests get JSON + the true status.
"""

from __future__ import annotations

import httpx

from tests.conftest import NAVIGATE_HEADERS
from tests.fakes import DEFAULT_APP_ID, DEFAULT_UPSTREAM, allow_response, deny_response


class TestAuthzCache:
    def test_authorize_cached_3s_by_cookie_hash_and_slug(self, logged_in, fake_backend, fake_manager, frozen_clock):
        """One RPC per (session, app) per 3s — and the route cache is separate."""
        for _ in range(3):
            logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert len(fake_backend.calls) == 1

        logged_in.get("/apps/bar", headers=NAVIGATE_HEADERS)
        assert len(fake_backend.calls) == 2, "a different slug is a different cache entry"

        logged_in.cookies.set("access_token_cookie", "a-different-session")
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert len(fake_backend.calls) == 3, "a different session is a different cache entry"

    def test_visibility_revoke_effective_after_cache_expiry(self, logged_in, fake_backend, frozen_clock):
        """AC-10 "from the next request" == "after the 3s window" (D6)."""
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200

        fake_backend.response = deny_response("forbidden")
        assert "无访问权限" not in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text, "still cached"

        frozen_clock.advance(3.1)
        assert "无访问权限" in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text
        assert len(fake_backend.calls) == 2

    def test_no_cookie_still_asks_backend_once_and_caches(self, proxy_client, fake_backend):
        """Anonymous traffic must not become a free RPC amplifier."""
        fake_backend.response = deny_response("login")
        proxy_client.get("/apps/foo", headers=NAVIGATE_HEADERS)
        proxy_client.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert len(fake_backend.calls) == 1

    def test_bearer_token_is_accepted_as_session(self, proxy_client, fake_backend):
        """``_extract_http_access_token`` takes cookie **or** Bearer; so do we."""
        proxy_client.get("/apps/foo", headers={**NAVIGATE_HEADERS, "Authorization": "Bearer platform-jwt"})
        assert fake_backend.calls[0]["access_token"] == "platform-jwt"


class TestAllow:
    def test_allow_forwards(self, logged_in, echo_upstream):
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200
        assert echo_upstream.requests, "an allowed request must reach the app"

    def test_slug_and_app_id_are_carried_to_the_right_peers(self, logged_in, fake_backend, fake_manager):
        """The backend is asked by **slug**, the manager by **app_id**.

        They are different keys on purpose: the slug is the product-visible URL
        (AC-25), the app id is the internal identity that survives a rename.
        """
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert fake_backend.calls[0]["slug"] == "foo"
        assert fake_manager.calls == [DEFAULT_APP_ID]


class TestFallbackPages:
    def test_forbidden_page_content(self, logged_in, fake_backend):
        """AC-28: name + owner + what to do + square. No apply-for-access in this version."""
        fake_backend.response = deny_response("forbidden", app_name="问卷小助手", owner_name="李四")
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        body = response.text
        assert "问卷小助手" in body
        assert "李四" in body
        assert "无访问权限" in body
        assert "租户管理员" in body
        assert "返回广场" in body
        assert "申请" not in body, "本版无在线申请入口"

    def test_stopped_page_content(self, logged_in, fake_backend):
        """AC-29: only visible-to-me apps ever show this page — the backend
        decides that; here we pin the copy."""
        fake_backend.response = deny_response("stopped", app_state="stopped")
        body = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text
        assert "已停用" in body
        assert "问卷小助手" in body
        assert "返回广场" in body

    def test_not_found_page_for_draft_pending_deleted_and_unknown(self, logged_in, fake_backend):
        """AC-29 anti-enumeration: four different truths, one indistinguishable page.

        Byte-for-byte identical, because a difference in length or wording is
        an oracle for "does this app exist".
        """
        rendered = []
        for _ in range(4):
            fake_backend.response = deny_response("not_found")
            rendered.append(logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text)
            # New session each round so the 3s authz cache cannot be what makes
            # the four renders identical.
            logged_in.cookies.set("access_token_cookie", f"session-{len(rendered)}")

        assert len(set(rendered)) == 1
        assert "不存在或未上线" in rendered[0]
        assert "返回广场" in rendered[0]
        assert "问卷小助手" not in rendered[0], "must not leak the name of an app you cannot see"

    def test_unknown_slug_shape_is_not_found_without_an_rpc(self, logged_in, fake_backend):
        """A path that cannot be a slug is answered locally — no oracle, no load."""
        response = logged_in.get("/apps/..%2f..%2fetc%2fpasswd", headers=NAVIGATE_HEADERS)
        assert response.status_code in (200, 404)
        assert fake_backend.calls == []

    def test_not_enabled_guide_page_not_404_or_5xx(self, logged_in, fake_backend):
        """AC-30: the layer is not installed → guidance, explicitly not 404/5xx."""
        fake_backend.response = deny_response("not_enabled")
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200
        assert "未启用应用工场" in response.text
        assert "超管" in response.text

    def test_pages_are_self_contained(self, logged_in, fake_backend):
        """No CDN, no fonts, no logo URL: this page is what the user sees when
        the platform is already half-broken."""
        fake_backend.response = deny_response("forbidden")
        body = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text
        assert "http://" not in body.replace("http://www.w3.org", "")
        assert "https://" not in body.replace("https://www.w3.org", "")
        assert "<script" not in body.lower(), "fallback pages need no JS (the login handoff does)"


class TestFailClosed:
    def test_backend_timeout_or_5xx_fail_closed(self, logged_in, fake_backend):
        """AC-12: no answer is a refusal, never a pass-through."""
        fake_backend.status_code = 500
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200
        assert "暂时无法" in response.text

        fake_backend.status_code = 200
        fake_backend.fail = httpx.ConnectTimeout("boom")
        assert "暂时无法" in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text

    def test_unknown_decision_is_refused(self, logged_in, fake_backend):
        """A backend rolled forward with a new verdict we don't understand must
        not accidentally mean "allow"."""
        fake_backend.response = {**allow_response(), "decision": "probably_fine"}
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert "暂时无法" in response.text

    def test_missing_hmac_secret_fails_closed(self, logged_in, fake_backend):
        from app_proxy import clients

        clients.get_backend_client().secret = ""
        assert "暂时无法" in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text
        assert fake_backend.calls == []

    def test_fail_closed_is_not_cached(self, logged_in, fake_backend):
        """Caching an outage would extend a 1s blip into a 3s one for everybody."""
        fake_backend.status_code = 500
        assert "暂时无法" in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text

        fake_backend.status_code = 200
        recovered = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert "暂时无法" not in recovered.text, "the blip must not linger for the rest of the TTL"
        assert len(fake_backend.calls) == 2, "the failed attempt was re-asked, not cached"


class TestRecovering:
    def test_recovering_static_page_on_upstream_unreachable(self, logged_in, upstream_transport):
        """AC-36 MVP shape: the crash / switch window is a page, not a 502.

        Static in this wave — no auto-retry (that is T082). Asserting the
        *absence* of the refresh meta keeps the two waves honest.
        """
        upstream_transport.refuse.add(DEFAULT_UPSTREAM)
        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200
        assert "恢复中" in response.text
        assert "http-equiv" not in response.text.lower()

    def test_no_live_instance_renders_recovering_not_an_error(self, logged_in, fake_manager):
        """The manager's 404 ("no instance right now") is an expected answer."""
        fake_manager.routes[DEFAULT_APP_ID] = None
        assert "恢复中" in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text
