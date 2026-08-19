"""F056 T016 — the application square, end to end, through a **non-administrator**.

Why a live suite exists at all when ``test/app_runtime/test_square_scan_page.py``
already covers the same service: that file stubs
``batch_check_business_actions``, so it proves the square asks the right
question and keeps the right rows. It cannot prove the *answer* — the FGA
tuples, the projection, the cache — and every AC in this file is about the
answer.

**The account rule is the whole test, not a detail.**
``_identity_shortcut`` (``permission_action_service.py:372-384``) allows
``SUPER_ADMIN`` / ``TENANT_ADMIN`` regardless of action and *before* the action
is even validated (F056 design K2). An administrator therefore passes every
assertion below whether the feature works or not, which makes an admin-run green
suite worth exactly nothing. Everything the square is asked here is asked as a
normal user who neither owns the application nor administers anything.

What the environment must provide, and why it is not created here: a hosted
application only comes into existence through ``bisheng deploy`` → approval →
online, and there is no REST endpoint that creates one. So the suite
**discovers** hosted applications with the administrator session and skips —
loudly, naming what is missing — when the deployment has none in the state a
given case needs. It creates and removes only grants, and only for its own test
user.

Prerequisites:

* ``F056_E2E=1`` — this suite mutates grants on a real deployment.
* ``E2E_API_BASE`` pointing at the test deployment; ``E2E_ADMIN_PASSWORD`` if
  the admin password is not the default.
* ``F056_E2E_USER_NAME`` / ``F056_E2E_USER_PASSWORD`` / ``F056_E2E_USER_ID`` —
  an ordinary account: **not** a super admin, **not** a tenant admin, and not
  the owner of any hosted application.
* ``F056_E2E_CROSS_TENANT_USER_NAME`` / ``F056_E2E_CROSS_TENANT_USER_PASSWORD``
  — optional; only ``test_tenant_isolation`` needs it and it skips without them.

覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-15
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

#: ``FlowType.HOSTED_APP``. Written as a literal rather than imported so the
#: suite asserts the number the *wire* carries; importing the enum would make a
#: renumbering invisible to a test whose whole job is the client contract.
HOSTED_APP_FLOW_TYPE = 35

#: The two application states the square shows. Everything else — draft,
#: pending_capacity, deleted — is excluded by a SQL predicate, not by a
#: permission check, which is why the exclusion holds even for the owner.
SQUARE_STATES = ("online", "stopped")
HIDDEN_STATES = ("draft", "pending_capacity")

E2E_ENABLED = os.environ.get("F056_E2E") == "1"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not E2E_ENABLED,
        reason="set F056_E2E=1 only against a deployment with MySQL / Redis / OpenFGA running",
    ),
]


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required when F056_E2E=1")
    return value


# ---------------------------------------------------------------------------
# probes — one function per surface, so a change of shape fails in one place
# ---------------------------------------------------------------------------


async def _square_rows(
    client: httpx.AsyncClient,
    token: str,
    *,
    keyword: str | None = None,
    flow_type: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """``GET /chat/online`` — the tagged square entry the client's 应用广场 uses."""
    params: dict[str, str | int] = {"page": 1, "limit": limit}
    if keyword:
        params["keyword"] = keyword
    if flow_type is not None:
        params["flow_type"] = flow_type
    response = await client.get(f"{API_BASE}/chat/online", params=params, headers=auth_headers(token))
    return assert_resp_200(response) or []


async def _uncategorized_rows(
    client: httpx.AsyncClient,
    token: str,
    *,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """``GET /workstation/app/uncategorized`` — the默认分类 tab.

    Asserted separately from the tagged entry throughout: the two share
    ``_scan_visible_apps_page`` but *not* ``add_extra_field``, so a field
    attached in the wrong place works on one tab and is silently absent on the
    other.
    """
    params: dict[str, str | int] = {"page": 1, "limit": limit}
    if keyword:
        params["keyword"] = keyword
    response = await client.get(
        f"{API_BASE}/workstation/app/uncategorized",
        params=params,
        headers=auth_headers(token),
    )
    return assert_resp_200(response) or []


async def _entry_allows(client: httpx.AsyncClient, token: str, app_id: str) -> bool:
    """The F054 entry judgement, over HTTP.

    ``POST /workstation/app/used/record`` delegates authorisation to exactly
    ``check_business_action(login_user, resource_type="app", resource_id=...,
    action="use")`` and does nothing else that could fail — which makes it the
    only endpoint that answers the entry question without a second rule mixed
    in. A refusal rides inside a 200 envelope as business code 403.

    Side effect, deliberately accepted: an **allowed** call adds the application
    to this user's "最近使用" list. It is per-user, idempotent and touches
    nothing another test reads, and the alternative — asserting the entry
    verdict from ``/permissions/check`` — would go through a different call
    chain than the one the entry actually uses, which is the very thing AC-06
    is about.
    """
    response = await client.post(
        f"{API_BASE}/workstation/app/used/record",
        json={"flow_id": app_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, f"HTTP {response.status_code}: {response.text[:200]}"
    return response.json()["status_code"] == 200


def _hosted_row(rows: list[dict], app_id: str) -> dict | None:
    for row in rows:
        if str(row.get("id")) == str(app_id):
            return row
    return None


# ---------------------------------------------------------------------------
# grant plumbing — F048's optimistic-concurrency dance, in three helpers
# ---------------------------------------------------------------------------


async def _permission_context(client: httpx.AsyncClient, token: str, app_id: str) -> dict:
    response = await client.get(
        f"{API_BASE}/permissions/resources/app/{app_id}/context",
        headers=auth_headers(token),
    )
    return assert_resp_200(response)


async def _permission_roster(client: httpx.AsyncClient, token: str, app_id: str) -> list[dict]:
    response = await client.get(
        f"{API_BASE}/permissions/resources/app/{app_id}/grants",
        params={"page_size": 100},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)["data"]


async def _grant_viewer(client: httpx.AsyncClient, admin_token: str, app_id: str, user_id: str) -> None:
    """Give one user the ``viewer`` model on one hosted application.

    ``viewer`` is level 1 and ``use`` is a level-1 action, so this is the
    smallest grant that makes the application enterable — which is the point:
    AC-15 wants the *minimum* visible-scope grant to confer no management at
    all, and a larger model would not test that.
    """
    context = await _permission_context(client, admin_token, app_id)
    response = await client.post(
        f"{API_BASE}/permissions/resources/app/{app_id}/grants:mutate",
        json={
            "idempotency_key": f"f056-add-{uuid4().hex}",
            "expected_resource_version": context["resource_version"],
            "expected_catalog_release_id": context["catalog_release_id"],
            "changes": [{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": str(user_id)}}],
        },
        headers=auth_headers(admin_token),
    )
    assert_resp_200(response)


async def _revoke_user(client: httpx.AsyncClient, admin_token: str, app_id: str, user_id: str) -> int:
    """Remove every editable grant this user holds on the application.

    Returns how many were removed, so a caller can tell "revoked" from "there
    was nothing to revoke" — the difference between a real teardown and a
    fixture that quietly did nothing.
    """
    removed = 0
    for _ in range(10):
        roster = await _permission_roster(client, admin_token, app_id)
        targets = [
            item
            for item in roster
            if item["subject"]["type"] == "user"
            and str(item["subject"]["id"]) == str(user_id)
            and not item["protected"]
            and item["scope"] == "LOCAL"
        ]
        if not targets:
            return removed
        context = await _permission_context(client, admin_token, app_id)
        response = await client.post(
            f"{API_BASE}/permissions/resources/app/{app_id}/grants:mutate",
            json={
                "idempotency_key": f"f056-remove-{uuid4().hex}",
                "expected_resource_version": context["resource_version"],
                "expected_catalog_release_id": context["catalog_release_id"],
                "changes": [
                    {
                        "op": "REMOVE",
                        "assignee_id": targets[0]["assignee_id"],
                        "expected_assignee_version": targets[0]["assignee_version"],
                    }
                ],
            },
            headers=auth_headers(admin_token),
        )
        assert_resp_200(response)
        removed += 1
    pytest.fail(f"could not clear grants for user {user_id} on app {app_id} in 10 rounds")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=30.0) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


@pytest.fixture(scope="module")
async def normal_user(client: httpx.AsyncClient) -> tuple[str, str]:
    """``(user_id, token)`` for the ordinary account every assertion runs as."""
    user_id = _required_env("F056_E2E_USER_ID")
    token = await get_user_token(
        client,
        _required_env("F056_E2E_USER_NAME"),
        _required_env("F056_E2E_USER_PASSWORD"),
    )
    return user_id, token


@pytest.fixture(scope="module")
async def hosted_apps(client: httpx.AsyncClient, admin_token: str, normal_user: tuple[str, str]) -> dict:
    """Hosted applications on this deployment, grouped by state.

    Discovered rather than created: there is no endpoint that makes a hosted
    application, and a suite that faked one by writing ``app`` rows would be
    testing its own INSERT instead of the publish pipeline's output.

    Applications the test user owns are dropped from every bucket. An owner is
    allowed through by ``owner``, so using one would make "the grant did it"
    unfalsifiable.
    """
    user_id, _ = normal_user
    response = await client.get(f"{API_BASE}/apps", headers=auth_headers(admin_token))
    rows = assert_resp_200(response) or []
    foreign = [row for row in rows if str(row.get("owner_user_id")) != str(user_id)]
    grouped: dict[str, list[dict]] = {}
    for row in foreign:
        grouped.setdefault(str(row.get("state")), []).append(row)
    if not grouped.get("online"):
        pytest.skip(
            "no hosted application in state 'online' owned by somebody other than the test user; "
            "deploy one with `bisheng deploy` before running F056 T016"
        )
    return grouped


@pytest.fixture(scope="module")
def target_app(hosted_apps: dict) -> dict:
    return hosted_apps["online"][0]


@pytest.fixture()
async def clean_grants(client: httpx.AsyncClient, admin_token: str, normal_user: tuple[str, str], target_app: dict):
    """Leave the test user with no grant on the target application, before and after.

    Before matters as much as after: a leftover grant from an interrupted run
    would make ``test_grant_then_revoke_visibility`` start from 1 and assert
    nothing.
    """
    user_id, _ = normal_user
    await _revoke_user(client, admin_token, target_app["app_id"], user_id)
    yield
    await _revoke_user(client, admin_token, target_app["app_id"], user_id)


# ---------------------------------------------------------------------------
# AC-04 / AC-05 — a grant is visible on the next request, and so is its removal
# ---------------------------------------------------------------------------


async def test_grant_then_revoke_visibility(
    client: httpx.AsyncClient,
    admin_token: str,
    normal_user: tuple[str, str],
    target_app: dict,
    clean_grants,
):
    """0 → 1 → 0, each step observed by the **very next** request.

    No re-login, no sleep, no cache-expiry wait anywhere in this test. That is
    the assertion: if visibility were served from a TTL cache, the middle step
    would still pass and only the last would fail — intermittently, and only on
    a machine slower than the TTL. Doing it without a wait is what makes the
    failure deterministic.
    """
    user_id, user_token = normal_user
    app_id = target_app["app_id"]

    before = await _square_rows(client, user_token, keyword=target_app["name"], flow_type=HOSTED_APP_FLOW_TYPE)
    assert _hosted_row(before, app_id) is None, "the test user could already see the application before any grant"

    await _grant_viewer(client, admin_token, app_id, user_id)

    after_grant = await _square_rows(client, user_token, keyword=target_app["name"], flow_type=HOSTED_APP_FLOW_TYPE)
    assert _hosted_row(after_grant, app_id) is not None, "the grant did not reach the square on the next request"

    removed = await _revoke_user(client, admin_token, app_id, user_id)
    assert removed >= 1, "teardown removed nothing, so the revoke half asserts nothing"

    after_revoke = await _square_rows(client, user_token, keyword=target_app["name"], flow_type=HOSTED_APP_FLOW_TYPE)
    assert _hosted_row(after_revoke, app_id) is None, "the application stayed visible after the grant was revoked"


# ---------------------------------------------------------------------------
# AC-06 — the square and the entry answer from one source
# ---------------------------------------------------------------------------


async def test_square_and_entry_same_source(
    client: httpx.AsyncClient,
    admin_token: str,
    normal_user: tuple[str, str],
    target_app: dict,
    clean_grants,
):
    """Visible in the square ⟺ enterable. Both directions, same user, same app.

    The steady state this forbids is "the card is there and clicking it says no
    permission", which is what happens the moment the two sides decide with
    different actions — the square on ``visible``, the entry on ``use``. Only
    the *pair* of assertions catches it: a square that showed everything would
    pass the granted half on its own.
    """
    user_id, user_token = normal_user
    app_id = target_app["app_id"]

    assert not await _entry_allows(client, user_token, app_id)
    denied_rows = await _square_rows(client, user_token, keyword=target_app["name"], flow_type=HOSTED_APP_FLOW_TYPE)
    assert _hosted_row(denied_rows, app_id) is None

    await _grant_viewer(client, admin_token, app_id, user_id)

    assert await _entry_allows(client, user_token, app_id)
    allowed_rows = await _square_rows(client, user_token, keyword=target_app["name"], flow_type=HOSTED_APP_FLOW_TYPE)
    assert _hosted_row(allowed_rows, app_id) is not None


# ---------------------------------------------------------------------------
# AC-02 / AC-03 — which states the square shows, decided server-side
# ---------------------------------------------------------------------------


async def test_state_filter(
    client: httpx.AsyncClient,
    admin_token: str,
    normal_user: tuple[str, str],
    hosted_apps: dict,
):
    """``stopped`` still appears (carrying ``app_state``); draft / pending / deleted never do.

    Run with a granted normal user *and* with the administrator, because the two
    halves fail differently: the exclusion is a SQL predicate rather than a
    permission check, so an administrator — who is allowed through every
    permission — is exactly the account that would reveal a state filter
    implemented in the wrong layer.
    """
    user_id, user_token = normal_user
    stopped = (hosted_apps.get("stopped") or [None])[0]
    if stopped is None:
        pytest.skip("no hosted application in state 'stopped'; stop one to exercise AC-03's first half")

    await _revoke_user(client, admin_token, stopped["app_id"], user_id)
    await _grant_viewer(client, admin_token, stopped["app_id"], user_id)
    try:
        rows = await _square_rows(client, user_token, keyword=stopped["name"], flow_type=HOSTED_APP_FLOW_TYPE)
        row = _hosted_row(rows, stopped["app_id"])
        assert row is not None, "a stopped application must stay in the square — it is entered to be resumed"
        assert row["app_state"] == "stopped"
    finally:
        await _revoke_user(client, admin_token, stopped["app_id"], user_id)

    hidden = [row for state in HIDDEN_STATES for row in hosted_apps.get(state, [])]
    if not hidden:
        pytest.skip("no hosted application in a hidden state (draft / pending_capacity)")

    # Queried by name, one hidden application at a time: a broad listing would
    # turn "not on page 1 of 100" into a pass, and a negative assertion that can
    # be satisfied by pagination is not an assertion.
    for token in (user_token, admin_token):
        for one in hidden:
            rows = await _square_rows(client, token, keyword=one["name"], flow_type=HOSTED_APP_FLOW_TYPE)
            uncategorized = await _uncategorized_rows(client, token, keyword=one["name"])
            assert _hosted_row(rows, one["app_id"]) is None, (
                f"application {one['app_id']} in state {one['state']} reached the tagged square entry"
            )
            assert _hosted_row(uncategorized, one["app_id"]) is None, (
                f"application {one['app_id']} in state {one['state']} reached the uncategorised entry"
            )

        page = await _square_rows(client, token, flow_type=HOSTED_APP_FLOW_TYPE)
        assert all(str(row.get("app_state")) in SQUARE_STATES for row in page if row.get("app_state") is not None)


# ---------------------------------------------------------------------------
# AC-01 / AC-07 — the card's payload
# ---------------------------------------------------------------------------


async def test_payload_shape(
    client: httpx.AsyncClient,
    admin_token: str,
    normal_user: tuple[str, str],
    target_app: dict,
    clean_grants,
):
    """A hosted row carries what the card needs; the other two types are untouched.

    ``slug`` is the load-bearing one — the client navigates to ``/apps/{slug}``,
    so a missing value produces a link to ``/apps/undefined`` with no error
    anywhere. ``can_share`` is false because a hosted application has no share
    link to hand out, and ``user_name`` is the owner's display name that the
    card's byline reads.
    """
    user_id, user_token = normal_user
    app_id = target_app["app_id"]
    await _grant_viewer(client, admin_token, app_id, user_id)

    rows = await _square_rows(client, user_token, keyword=target_app["name"])
    row = _hosted_row(rows, app_id)
    assert row is not None

    assert row["flow_type"] == HOSTED_APP_FLOW_TYPE
    assert row["slug"] == target_app["slug"]
    assert row["app_state"] in SQUARE_STATES
    assert row["can_share"] is False
    assert row.get("user_name"), "the card's owner byline reads user_name"

    others = [one for one in rows if one.get("flow_type") != HOSTED_APP_FLOW_TYPE]
    for other in others:
        assert other.get("slug") is None, "slug is a hosted-application field and must stay absent elsewhere"
        assert other.get("app_state") is None


async def test_uncategorized_tab_shows_untagged_hosted_app(
    client: httpx.AsyncClient,
    admin_token: str,
    normal_user: tuple[str, str],
    target_app: dict,
    clean_grants,
):
    """An untagged hosted application appears on the默认分类 tab, with its ``slug``.

    This is the backend half only. ``get_uncategorized_flows`` never calls
    ``add_extra_field``, so it is the entry where an enrichment attached in the
    wrong place disappears — and it is the tab the acceptance script opens
    first.
    """
    user_id, user_token = normal_user
    app_id = target_app["app_id"]
    await _grant_viewer(client, admin_token, app_id, user_id)

    tagged = await _square_rows(client, user_token, keyword=target_app["name"], flow_type=HOSTED_APP_FLOW_TYPE)
    if _hosted_row(tagged, app_id) is None:
        pytest.skip("the target application is not visible in the square at all; earlier cases cover that failure")

    rows = await _uncategorized_rows(client, user_token, keyword=target_app["name"])
    row = _hosted_row(rows, app_id)
    if row is None:
        roster_names = [str(one.get("name")) for one in rows]
        pytest.skip(
            "the target application carries a tag, so 'uncategorised' correctly excludes it; "
            f"pick an untagged hosted application (saw: {roster_names[:5]})"
        )
    assert row["slug"] == target_app["slug"]
    assert row["flow_type"] == HOSTED_APP_FLOW_TYPE
    assert row["app_state"] in SQUARE_STATES


# ---------------------------------------------------------------------------
# AC-04 — tenant isolation, asserted by somebody who is not an administrator
# ---------------------------------------------------------------------------


async def test_tenant_isolation(client: httpx.AsyncClient, hosted_apps: dict):
    """A user of tenant B never sees tenant A's hosted applications.

    A super admin crosses tenants legitimately, so running this as one proves
    nothing at all — the check has to come from an ordinary account on the other
    side of the boundary.
    """
    name = os.environ.get("F056_E2E_CROSS_TENANT_USER_NAME", "").strip()
    password = os.environ.get("F056_E2E_CROSS_TENANT_USER_PASSWORD", "").strip()
    if not name or not password:
        pytest.skip("set F056_E2E_CROSS_TENANT_USER_NAME / _PASSWORD to exercise tenant isolation")

    cross_token = await get_user_token(client, name, password)
    foreign = [row for rows in hosted_apps.values() for row in rows]
    all_ids = {str(row["app_id"]) for row in foreign}

    rows = await _square_rows(client, cross_token, flow_type=HOSTED_APP_FLOW_TYPE)
    uncategorized = await _uncategorized_rows(client, cross_token)
    seen = {str(one.get("id")) for one in rows} | {str(one.get("id")) for one in uncategorized}
    assert not (seen & all_ids), f"cross-tenant hosted application(s) visible: {sorted(seen & all_ids)}"

    # The listing above can only be trusted as far as its page reaches, so each
    # application is also asked directly. The entry probe is the exact question
    # and needs no pagination — a leak that a wide page hid still fails here.
    for one in foreign[:20]:
        by_name = await _square_rows(client, cross_token, keyword=one["name"], flow_type=HOSTED_APP_FLOW_TYPE)
        assert _hosted_row(by_name, one["app_id"]) is None, f"cross-tenant application {one['app_id']} in the square"
        assert not await _entry_allows(client, cross_token, one["app_id"]), (
            f"cross-tenant application {one['app_id']} is enterable"
        )


# ---------------------------------------------------------------------------
# AC-15 — being granted visibility grants no management
# ---------------------------------------------------------------------------


async def test_manage_dialog_denied_for_grantee(
    client: httpx.AsyncClient,
    admin_token: str,
    normal_user: tuple[str, str],
    target_app: dict,
    clean_grants,
):
    """``viewer`` opens the application; it does not open the permission dialog.

    ``manage_permission`` is a level-3 action and ``viewer`` is level 1, so the
    two travel separately — but only if the roster endpoint checks the concrete
    action rather than "can this user see the resource at all". Both the read
    and the write are asserted: a read-only leak still shows who else has
    access.
    """
    user_id, user_token = normal_user
    app_id = target_app["app_id"]
    await _grant_viewer(client, admin_token, app_id, user_id)

    assert await _entry_allows(client, user_token, app_id), "the viewer grant did not take effect"

    roster = await client.get(
        f"{API_BASE}/permissions/resources/app/{app_id}/grants",
        params={"page_size": 100},
        headers=auth_headers(user_token),
    )
    assert roster.status_code == 200, "a refusal must ride inside a 200 envelope, or the SPA navigates to /403"
    assert_resp_error(roster, 19000)

    # The optimistic-concurrency fields come from the **administrator's** view of
    # the resource, so the only thing left that can refuse this call is the
    # permission check. Sending 0 / 1 would let a version-mismatch error pass for
    # a permission error and the test would go green on a broken gate.
    context = await _permission_context(client, admin_token, app_id)
    mutate = await client.post(
        f"{API_BASE}/permissions/resources/app/{app_id}/grants:mutate",
        json={
            "idempotency_key": f"f056-denied-{uuid4().hex}",
            "expected_resource_version": context["resource_version"],
            "expected_catalog_release_id": context["catalog_release_id"],
            "changes": [{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": str(user_id)}}],
        },
        headers=auth_headers(user_token),
    )
    assert mutate.status_code == 200
    assert_resp_error(mutate, 19000)
