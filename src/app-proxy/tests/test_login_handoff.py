"""AC-27 — getting an unauthenticated visitor to the login page and back.

The hard part is not the redirect, it is coming *back* to the same address.
Two facts make the obvious 302 impossible (坑 11):

* a URL fragment is never sent to a server, so ``/apps/foo?a=1#b`` arrives here
  as ``/apps/foo?a=1`` — the ``#b`` a QR code carried is already gone;
* the platform login page consumes **only** ``localStorage.LOGIN_PATHNAME`` +
  ``LOGIN_PATHNAME_AT``. It does not read ``?redirect=``, so there is nothing
  to hand a return address to server-side.

Hence a tiny inline-JS handoff page: the browser is the only party that can
still see the full address, so it is the one that writes it down.
"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import NAVIGATE_HEADERS, XHR_HEADERS
from tests.fakes import deny_response


@pytest.fixture
def anonymous(proxy_client, fake_backend):
    fake_backend.response = deny_response("login")
    return proxy_client


class TestHandoffPage:
    def test_navigation_gets_inline_js_handoff(self, anonymous):
        response = anonymous.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        body = response.text
        assert "<script>" in body
        assert "localStorage" in body
        assert "location.replace" in body

    def test_query_and_hash_preserved(self, anonymous):
        """The stored value must be ``location.href``, evaluated in the browser.

        Anything the server renders into the page is missing the fragment by
        construction, so this asserts the *mechanism*, not a string: had we
        templated the request URL in, ``#b`` would be silently lost and the
        symptom ("scanned link opens a blank app after login") would surface
        only on links that carry parameters.
        """
        body = anonymous.get("/apps/foo?a=1", headers=NAVIGATE_HEADERS).text

        assert "location.href" in body
        assert "/apps/foo?a=1" not in body, "the return address must not be server-rendered"

    def test_key_names_and_ttl_match_platform_contract(self, anonymous):
        """Cross-SPA contract with ``platform/utils/loginReturnTo.ts``.

        Key names, the millisecond timestamp and the ``/admin`` destination are
        all load bearing: the consumer drops the value if the stamp is older
        than 10 minutes, and it is the *only* reader of these keys.
        """
        body = anonymous.get("/apps/foo", headers=NAVIGATE_HEADERS).text

        assert "LOGIN_PATHNAME" in body
        assert "LOGIN_PATHNAME_AT" in body
        assert "Date.now()" in body
        assert "/admin" in body

    def test_handoff_page_survives_disabled_storage(self, anonymous):
        """Private mode with storage blocked must still reach the login page.

        Losing the return address is a papercut; a JS exception before
        ``location.replace`` leaves the visitor staring at a blank page.
        """
        body = anonymous.get("/apps/foo", headers=NAVIGATE_HEADERS).text
        assert "try" in body and "catch" in body

    def test_handoff_page_is_not_indexable_and_has_no_external_asset(self, anonymous):
        body = anonymous.get("/apps/foo", headers=NAVIGATE_HEADERS).text
        assert "noindex" in body
        assert "//" not in body.replace("http://www.w3.org", "").replace("location.href", "")


class TestNonNavigationSplit:
    @pytest.mark.parametrize(
        ("decision", "status", "code"),
        [
            ("login", 401, 16141),
            ("forbidden", 403, 16142),
            ("stopped", 403, 16143),
            ("not_found", 404, 16144),
            ("not_enabled", 503, 16145),
        ],
    )
    def test_xhr_gets_json_and_real_status(self, logged_in, fake_backend, decision, status, code):
        """An in-app ``fetch()`` that receives an HTML page parses it and dies
        somewhere unrelated. Give it the truth in the shape it expects."""
        fake_backend.response = deny_response(decision)
        response = logged_in.get("/apps/foo/api/data", headers=XHR_HEADERS)

        assert response.status_code == status
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["status_code"] == code
        assert response.json()["decision"] == decision

    def test_accept_html_without_sec_fetch_still_gets_a_page(self, anonymous):
        """Older browsers (and 信创 builds) send no ``Sec-Fetch-*`` at all."""
        response = anonymous.get("/apps/foo", headers={"Accept": "text/html,application/xhtml+xml"})
        assert response.headers["content-type"].startswith("text/html")

    def test_bare_request_is_treated_as_programmatic(self, anonymous):
        """No navigation signal at all → JSON. curl and health probes land here."""
        response = anonymous.get("/apps/foo", headers={"Accept": "*/*"})
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")

    def test_sec_fetch_wins_over_accept(self, logged_in, fake_backend):
        """``fetch('/x', {headers:{Accept:'text/html'}})`` is still not a navigation."""
        fake_backend.response = deny_response("forbidden")
        response = logged_in.get(
            "/apps/foo", headers={"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "Accept": "text/html"}
        )
        assert response.headers["content-type"].startswith("application/json")


class TestWebSocketRefusal:
    @pytest.mark.parametrize(
        ("decision", "close_code"),
        [("login", 4401), ("forbidden", 4403), ("stopped", 4403), ("not_found", 4404), ("not_enabled", 4503)],
    )
    def test_ws_upgrade_rejected_with_close_code(self, proxy_client, fake_backend, decision, close_code):
        """A refused upgrade must not become an HTML page: the client is a
        WebSocket, and the only thing it can read is a close code."""
        fake_backend.response = deny_response(decision)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with proxy_client.websocket_connect("/apps/foo/ws"):
                pass
        assert excinfo.value.code == close_code

    def test_ws_refused_while_proxying_is_not_yet_enabled(self, proxy_client, fake_backend):
        """Allowed, but WS reverse proxying is Wave 4 (T079/T080).

        A distinct code so the 114 walkthrough can tell "you may not" from
        "not built yet" without reading logs.
        """
        proxy_client.cookies.set("access_token_cookie", "jwt-token-for-tests")
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with proxy_client.websocket_connect("/apps/foo/ws"):
                pass
        assert excinfo.value.code == 4501
