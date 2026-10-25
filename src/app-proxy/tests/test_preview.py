"""T090a (reverse-proxy half) — ``/apps/preview/{session}`` (AC-25 / AC-32 / AC-37).

Three properties, and the first is the reason this file exists at all:

* **It is the same strip / inject code, not a second copy.** The assertions go
  through the real upstream: the forged ``X_BiSheng_User_Id`` is gone, the
  platform session cookie is gone, and the ten identity headers plus
  ``X-Forwarded-Prefix`` arrive — exactly as on ``/apps/{slug}``. A preview path
  that grew its own header handling is how ``X_Forwarded_User`` walked past
  oauth2-proxy (CVE-2025-64484).
* **The prefix that comes off is the preview's own.** ``/apps/preview/{s}/x``
  reaches the app as ``/x`` and ``X-Forwarded-Prefix`` is
  ``/apps/preview/{s}`` — so the same source runs unchanged at both entries.
* **The lifecycle is not here.** app-proxy never starts or reclaims a preview
  (that is F055's); a missing upstream is the ordinary transitional page, not a
  502 and not an attempt to bring something up.
"""

from __future__ import annotations

import pytest

from tests.conftest import NAVIGATE_HEADERS, XHR_HEADERS
from tests.fakes import DEFAULT_PREVIEW_SESSION, DEFAULT_UPSTREAM, deny_response, preview_allow_response

SESSION = DEFAULT_PREVIEW_SESSION
BASE = f"/apps/preview/{SESSION}"


@pytest.fixture()
def preview_ready(fake_backend, fake_manager):
    """The happy path: the verdict allows, and the manager has a preview route."""
    fake_backend.preview_response = preview_allow_response()
    fake_manager.routes[SESSION] = {"upstream": DEFAULT_UPSTREAM, "version_id": "ver-pending", "generation": 0}
    return fake_backend, fake_manager


def _headers(request) -> dict[str, str]:
    return {name.lower(): value for name, value in request["headers"]}


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------


def test_the_preview_entry_asks_the_preview_endpoint(logged_in, preview_ready):
    backend, _manager = preview_ready

    assert logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS).status_code == 200

    assert backend.paths == ["/api/v1/internal/app-proxy/authorize-preview"]
    assert backend.calls[0]["session"] == SESSION
    assert "slug" not in backend.calls[0]


def test_the_upstream_is_resolved_by_session_not_by_app_id(logged_in, preview_ready):
    """A preview has no desired-state record, so ``/v1/apps/{id}/route`` would 404."""
    _backend, manager = preview_ready

    logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    assert manager.paths == [f"/v1/previews/{SESSION}/route"]


def test_a_refused_preview_renders_the_not_found_page(logged_in, fake_backend):
    """AC-37 — and it carries no application name: nothing may leak from here."""
    fake_backend.preview_response = deny_response("not_found")

    response = logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "问卷小助手" not in response.text


def test_a_refused_preview_answers_json_to_a_programmatic_caller(logged_in, fake_backend):
    fake_backend.preview_response = deny_response("not_found")

    response = logged_in.get(f"{BASE}/api/things", headers=XHR_HEADERS)

    assert response.status_code == 404
    assert response.json()["status_code"] == 16144


def test_no_session_hands_off_to_login(proxy_client, fake_backend):
    fake_backend.preview_response = deny_response("login")

    response = proxy_client.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_an_unknown_verdict_is_refused_rather_than_forwarded(logged_in, fake_backend, echo_upstream):
    """AC-12 — a backend ahead of this build must never fall through to forward."""
    fake_backend.preview_response = {"decision": "definitely-come-in", "headers": {}}

    response = logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    assert response.status_code == 200
    assert echo_upstream.requests == []


def test_a_malformed_session_is_answered_locally(logged_in, fake_backend):
    """Scanner traffic never becomes an RPC — the shape is checked here first."""
    for bad in ("short", "has%20space", "a" * 80):
        response = logged_in.get(f"/apps/preview/{bad}/", headers=NAVIGATE_HEADERS)
        # The platform's own "does not exist" page, rendered without asking
        # anybody: 200 + HTML for a navigation, like every other verdict page.
        assert response.status_code == 200, bad
        assert "text/html" in response.headers["content-type"], bad

    assert fake_backend.calls == []


def test_a_traversal_attempt_never_reaches_the_handler(logged_in, fake_backend):
    """``/apps/preview/../..`` is normalised away before routing — no RPC either."""
    response = logged_in.get("/apps/preview/../..", headers=NAVIGATE_HEADERS)

    assert response.status_code == 404
    assert fake_backend.calls == []


# ---------------------------------------------------------------------------
# the forward — same strip / inject code as the application entry (AC-32)
# ---------------------------------------------------------------------------


def test_forged_platform_headers_are_stripped(logged_in, preview_ready, echo_upstream):
    logged_in.get(
        f"{BASE}/",
        headers={
            **NAVIGATE_HEADERS,
            "X_BiSheng_User_Id": "1",
            "X-BiSheng-Tenant-Id": "999",
            "X-BiSheng-Subject-Kind": "service_account",
        },
    )

    sent = _headers(echo_upstream.requests[-1])
    assert sent["x-bisheng-user-id"] == "42"
    assert sent["x-bisheng-tenant-id"] == "1"
    assert sent["x-bisheng-subject-kind"] == "human"


def test_the_platform_session_cookie_never_reaches_the_preview(logged_in, preview_ready, echo_upstream):
    logged_in.cookies.set("app_own_cookie", "keep-me")

    logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    cookie = _headers(echo_upstream.requests[-1]).get("cookie", "")
    assert "access_token_cookie" not in cookie
    assert "app_own_cookie=keep-me" in cookie


def test_the_identity_material_and_the_obo_token_are_injected(logged_in, preview_ready, echo_upstream):
    logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    sent = _headers(echo_upstream.requests[-1])
    assert sent["x-bisheng-access-token"] == "obo.preview.token"
    assert sent["x-bisheng-app-id"] == "app-0001"
    assert sent["x-bisheng-request-id"]


def test_the_prefix_stripped_is_the_previews_own(logged_in, preview_ready, echo_upstream):
    """AC-25 — and the app is told the prefix so it can rebuild absolute URLs."""
    logged_in.get(f"{BASE}/reports/monthly?q=1", headers=NAVIGATE_HEADERS)

    request = echo_upstream.requests[-1]
    assert request["path"] == "/reports/monthly"
    assert request["query"] == "q=1"
    assert _headers(request)["x-forwarded-prefix"] == BASE


def test_the_bare_preview_root_redirects_to_a_trailing_slash(logged_in, preview_ready):
    """Same relative-URL trap as ``/apps/{slug}``: ``./assets/x.js`` must resolve inside."""
    response = logged_in.get(BASE, headers=NAVIGATE_HEADERS, follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == f"{BASE}/"


def test_a_post_to_the_bare_root_is_forwarded_not_redirected(logged_in, preview_ready, echo_upstream):
    response = logged_in.post(BASE, headers=NAVIGATE_HEADERS, json={"a": 1}, follow_redirects=False)

    assert response.status_code == 200
    assert echo_upstream.requests[-1]["path"] == "/"


# ---------------------------------------------------------------------------
# lifecycle is not controlled here (AC-37)
# ---------------------------------------------------------------------------


def test_a_missing_preview_upstream_renders_the_transitional_page(logged_in, fake_backend, fake_manager):
    """app-proxy neither starts nor reclaims a preview — it only reports."""
    fake_backend.preview_response = preview_allow_response()
    fake_manager.routes[SESSION] = None

    response = logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["Retry-After"]
    # Only the route lookup happened: no intent was sent to bring anything up.
    assert fake_manager.paths == [f"/v1/previews/{SESSION}/route"]
    assert all(path.endswith("/route") for path in fake_manager.paths)


def test_the_preview_and_the_application_caches_do_not_cross_serve(logged_in, preview_ready, fake_manager):
    """An app whose slug equals a session id must not be served the preview's route."""
    fake_manager.routes["app-0001"] = {"upstream": "http://172.20.0.99:8080", "version_id": "v1", "generation": 1}

    logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)
    logged_in.get("/apps/sales/", headers=NAVIGATE_HEADERS)

    assert f"/v1/previews/{SESSION}/route" in fake_manager.paths
    assert "/v1/apps/app-0001/route" in fake_manager.paths


def test_an_application_slug_named_preview_cannot_shadow_the_entry(logged_in, preview_ready, fake_backend):
    """The route order is deliberate; the backend reserves the name to match."""
    response = logged_in.get(f"{BASE}/", headers=NAVIGATE_HEADERS)

    assert response.status_code == 200
    assert fake_backend.paths == ["/api/v1/internal/app-proxy/authorize-preview"]
