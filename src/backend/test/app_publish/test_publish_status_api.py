"""T040 — the ``/api/v1`` publish endpoints the platform face calls (AC-32 / AC-34 / AC-38 / AC-62).

Session-authenticated, and only two of them. What is asserted most carefully is
the shape of a **refusal**: the platform SPA's response interceptor navigates
the entire page to ``/403`` on a real 403 or 404, so a non-owner opening a
colleague's application would lose the detail page rather than see a read-only
block (design 坑 22). Every refusal here has to arrive as HTTP 200 carrying a
business code.

The withdraw path is asserted by its **absence**: it belongs to the approval
centre's existing endpoint, which already refuses anybody who is not the
applicant — and the applicant is the owner. A second endpoint would be a second
place for that rule to live.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID, SUPER_ADMIN_USER_ID

pytestmark = pytest.mark.asyncio


def _body(response):
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def state_actions(monkeypatch):
    from bisheng.app_runtime.domain.services.app_state_service import ActionResult, AppStateService

    responses: dict[str, object] = {"manual_publish": ActionResult(app_id="app", state="online", ok=True)}

    async def _manual(app_id, *, actor=None):
        value = responses["manual_publish"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(AppStateService, "manual_publish", staticmethod(_manual))
    return SimpleNamespace(responses=responses)


async def _parked(app_factory, deployment_factory):
    app, version = await app_factory(state="pending_capacity", with_version=True)
    await deployment_factory(
        app_id=app.id,
        stage="pending_online",
        status="succeeded",
        version_id=version.id,
        tier_code="light",
        failure={
            "stage": "pending_online",
            "code": 16226,
            "message": "parked",
            "details": {"reason": "capacity"},
            "hints": [],
        },
    )
    return app, version


# ---------------------------------------------------------------------------
# AC-38 — the read endpoint
# ---------------------------------------------------------------------------


async def test_publish_status_endpoint_path_and_shape(publish_db, api_app, app_factory, owner_user, tier_seed):
    """``GET /api/v1/apps/{app_id}/publish-status``, pinned here for the face and for F052."""
    app, _ = await app_factory(with_version=True)

    async with api_app(payload=owner_user.payload) as client:
        payload = _body(await client.get(f"/api/v1/apps/{app.id}/publish-status"))

    data = payload["data"]
    assert set(data) == {
        "app_id",
        "app_state",
        "pending_reason",
        "current_version",
        "pending_version",
        "deployment",
        "approval",
        "tier",
        "capabilities",
        "schema_change",
        "can",
    }
    assert data["app_id"] == app.id


async def test_publish_status_non_owner_gets_business_code_not_403_404(publish_db, api_app, app_factory, tier_seed):
    """The refusal has to be renderable, or the whole detail page navigates away."""
    from bisheng.common.dependencies.user_deps import UserPayload

    app, _ = await app_factory(with_version=True)
    stranger = UserPayload(user_id=OWNER_USER_ID + 4242, user_name="stranger", user_role=[], tenant_id=ROOT_TENANT_ID)

    async with api_app(payload=stranger) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/publish-status")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16254


async def test_missing_app_is_also_a_200_envelope(publish_db, api_app, owner_user):
    """A 404 would navigate the SPA away just as surely as a 403."""
    async with api_app(payload=owner_user.payload) as client:
        response = await client.get("/api/v1/apps/no-such-app/publish-status")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16254


async def test_status_reports_pending_reason_through_http(
    publish_db, api_app, app_factory, deployment_factory, owner_user, tier_seed
):
    app, _ = await _parked(app_factory, deployment_factory)

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/publish-status"))["data"]

    assert data["app_state"] == "pending_capacity"
    assert data["pending_reason"] == "capacity"
    assert data["can"]["manual_publish"] is True


async def test_all_endpoints_return_unified_response_model(
    publish_db, api_app, app_factory, deployment_factory, owner_user, state_actions, audit_sink, tier_seed
):
    """Both endpoints answer with the platform envelope, success and refusal alike."""
    app, _ = await _parked(app_factory, deployment_factory)

    async with api_app(payload=owner_user.payload) as client:
        read = _body(await client.get(f"/api/v1/apps/{app.id}/publish-status"))
        action = _body(await client.post(f"/api/v1/apps/{app.id}/publish/manual-publish"))

    for payload in (read, action):
        assert set(payload) >= {"status_code", "status_message", "data"}
        assert payload["status_code"] == 200


# ---------------------------------------------------------------------------
# AC-32 / AC-62 — the action endpoint
# ---------------------------------------------------------------------------


async def test_manual_publish_endpoint_owner_only_16254(
    publish_db, api_app, app_factory, deployment_factory, state_actions, audit_sink, tier_seed
):
    """A super admin is refused — no permission check could express that.

    The runtime short-circuits ``is_global_super`` to ALLOW before ReBAC is
    consulted, so owner-only has to be a business pre-check.
    """
    from bisheng.common.dependencies.user_deps import UserPayload

    app, _ = await _parked(app_factory, deployment_factory)
    admin = UserPayload(
        user_id=SUPER_ADMIN_USER_ID, user_name="admin", user_role=[], tenant_id=ROOT_TENANT_ID, is_global_super=True
    )

    async with api_app(payload=admin) as client:
        response = await client.post(f"/api/v1/apps/{app.id}/publish/manual-publish")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16254


async def test_manual_publish_endpoint_succeeds_for_owner(
    publish_db, api_app, app_factory, deployment_factory, owner_user, state_actions, audit_sink, tier_seed
):
    app, version = await _parked(app_factory, deployment_factory)

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.post(f"/api/v1/apps/{app.id}/publish/manual-publish"))["data"]

    assert data["status"] == "online"
    assert data["version_id"] == version.id


async def test_withdraw_goes_through_existing_approval_endpoint(publish_db):
    """F055 adds no withdraw endpoint; the approval centre already owns one.

    ``withdraw_instance`` refuses anybody who is not ``applicant_user_id``, and
    the applicant *is* the owner (AC-16) — so owner-only is already enforced
    there. Adding a second endpoint would duplicate the rule and eventually
    disagree with it.
    """
    from bisheng.app_publish.api.router import v1_router
    from bisheng.approval.api.endpoints.approval_user import router as approval_user_router

    ours = {route.path for route in v1_router.routes}
    assert not any("withdraw" in path for path in ours)
    assert any("withdraw" in route.path for route in approval_user_router.routes)


async def test_tenant_admin_check_uses_the_apps_tenant_not_the_callers(
    publish_db, api_app, app_factory, tier_seed, monkeypatch
):
    """A tenant administrator is admitted for **their** tenant's applications only.

    The check has to be asked with ``app.tenant_id``. Asking it with the
    caller's tenant instead would admit a child-tenant administrator to a Root
    application — the caller is an administrator *somewhere*, and the question
    would never mention which application. Asserted by recording the arguments,
    because both spellings return True in the single-tenant happy path.
    """
    from bisheng.app_publish.domain.services import publish_status_service
    from bisheng.common.dependencies.user_deps import UserPayload

    from .conftest import SUB_TENANT_ID

    asked: list[tuple[int, int]] = []

    async def _check(user_id: int, tenant_id: int) -> bool:
        asked.append((user_id, tenant_id))
        return False

    monkeypatch.setattr(publish_status_service, "check_tenant_admin", _check)
    app, _ = await app_factory(tenant_id=SUB_TENANT_ID, owner_user_id=OWNER_USER_ID + 31, with_version=True)
    caller = UserPayload(user_id=OWNER_USER_ID + 99, user_name="other", user_role=[], tenant_id=ROOT_TENANT_ID)

    async with api_app(payload=caller) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/publish-status")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16254
    assert asked == [(caller.user_id, SUB_TENANT_ID)]


async def test_v1_router_carries_no_open_api_credential_dependency(publish_db):
    """These are session endpoints; a service-account key must not reach them.

    Merging the two routers would put a cookie-authenticated endpoint one typo
    away from being callable with ``Bearer bs-sak-…``.
    """
    from bisheng.app_publish.api.endpoints.deploy import app_manage_subject
    from bisheng.app_publish.api.router import v1_router

    for route in v1_router.routes:
        names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
        assert app_manage_subject.__name__ not in names
