"""T065 — ``/api/v1/resource-tiers``: the super admin's tier tab (AC-45 / AC-47).

What this file pins, and why each one is a test rather than a code comment:

* **The route table has no ``DELETE`` and no ``POST``.** "Tiers cannot be
  deleted" is an invariant F054 relies on (``tier_id`` always resolves), and
  the service-level test already covers the DAO. The HTTP layer is the third
  place somebody could add a delete, so the assertion is on the router's
  routes, not on a behaviour that only fails once the route is called.
* **A tenant administrator is refused with a business code**, not an HTTP
  403 — the platform SPA navigates the whole page to ``/403`` on a real one.
* **Disabling blocks new selections only.** The same tier that just answered
  ``enabled=false`` still resolves for a frozen ``app_version.tier_id``, and
  the apps counted as "in use" are still counted.
* **The default tier cannot be retired.** Every manifest without ``tier:``
  resolves to it (AC-46); retiring it would turn a platform-wide outage into a
  per-manifest 16223.
"""

from __future__ import annotations

import pytest

from .conftest import ROOT_TENANT_ID, SUPER_ADMIN_USER_ID

# ``asyncio_mode=auto`` — no module-level asyncio mark, this file mixes sync
# route-table checks with async endpoint tests.

LIST_URL = "/api/v1/resource-tiers"


def _body(response):
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------


def test_tier_routes_offer_no_delete_and_no_create():
    """AC-47's precondition at the HTTP layer: retirement is a PATCH, never a DELETE."""
    from bisheng.app_publish.api.router import v1_router

    tier_routes = [route for route in v1_router.routes if route.path.startswith("/resource-tiers")]
    assert tier_routes, "the tier admin endpoints are not mounted on the v1 router"
    methods = {method for route in tier_routes for method in route.methods}
    assert methods == {"GET", "PATCH"}, f"unexpected tier admin methods: {sorted(methods)}"
    assert {route.path for route in tier_routes} == {"/resource-tiers", "/resource-tiers/{tier_code}"}


def test_tier_routes_are_not_under_apps_prefix():
    """F054's ``GET /apps/{app_id}`` is mounted first and would swallow ``/apps/resource-tiers``."""
    from bisheng.app_publish.api.router import v1_router

    assert not any(route.path.startswith("/apps/resource-tiers") for route in v1_router.routes)


# ---------------------------------------------------------------------------
# Gates — super admin only, runtime layer must be on
# ---------------------------------------------------------------------------


async def test_list_refuses_non_super_admin_with_16260(publish_db, api_app, tier_seed, owner_user, tenant_admin_user):
    """A tenant administrator is not a platform super admin; both arrive as a business code."""
    for who in (owner_user, tenant_admin_user):
        async with api_app(payload=who.payload) as client:
            payload = _body(await client.get(LIST_URL))
        assert payload["status_code"] == 16260, payload
        async with api_app(payload=who.payload) as client:
            payload = _body(await client.patch(f"{LIST_URL}/light", json={"name": "x"}))
        assert payload["status_code"] == 16260, payload


async def test_list_refuses_when_runtime_layer_disabled_16207(publish_db, api_app, tier_seed, super_admin_user):
    """The tab is hidden when the layer is off; the endpoint says so too rather than listing tiers nobody can use."""
    async with api_app(payload=super_admin_user.payload, app_runtime_enabled=False) as client:
        payload = _body(await client.get(LIST_URL))
    assert payload["status_code"] == 16207, payload


async def test_rbac_admin_role_is_accepted_as_super_admin(publish_db, api_app, tier_seed):
    """The ``AdminRole`` fallback — payloads built without the login path still pass."""
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.database.constants import AdminRole

    payload = UserPayload(
        user_id=SUPER_ADMIN_USER_ID,
        user_name="rbac-admin",
        user_role=[AdminRole],
        tenant_id=ROOT_TENANT_ID,
        is_global_super=False,
    )
    async with api_app(payload=payload) as client:
        body = _body(await client.get(LIST_URL))
    assert body["status_code"] == 200, body


# ---------------------------------------------------------------------------
# AC-45 — list shape
# ---------------------------------------------------------------------------


async def test_list_shape_and_in_use_counts(publish_db, api_app, tier_seed, super_admin_user, app_factory):
    """Name / CPU / memory / guidance / enabled / in-use count, in display order, retired tiers included."""
    await app_factory(tier_id="light", terminal_state="online")
    await app_factory(tier_id="light", terminal_state="online")
    await app_factory(tier_id="light", terminal_state="rejected")
    await app_factory(tier_id="standard", terminal_state="online")

    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.get(LIST_URL))

    rows = payload["data"]
    assert [row["code"] for row in rows] == ["light", "standard", "performance"]
    assert set(rows[0]) == {
        "code",
        "name",
        "cpu_millicores",
        "memory_mb",
        "description",
        "enabled",
        "sort_order",
        "in_use_app_count",
        "is_default",
        "update_time",
    }
    counts = {row["code"]: row["in_use_app_count"] for row in rows}
    assert counts == {"light": 2, "standard": 1, "performance": 0}
    assert {row["code"]: row["is_default"] for row in rows} == {"light": True, "standard": False, "performance": False}
    assert all(row["enabled"] is True for row in rows)
    assert all(row["description"] for row in rows), "every tier ships plain-language guidance (AC-44)"


# ---------------------------------------------------------------------------
# AC-45 — inline edit
# ---------------------------------------------------------------------------


async def test_patch_retunes_spec_and_description_and_audits(
    publish_db, api_app, tier_seed, super_admin_user, audit_sink
):
    from bisheng.app_runtime.domain.constants import AppAuditAction

    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(
            await client.patch(
                f"{LIST_URL}/standard",
                json={"cpu_millicores": 1500, "memory_mb": 3072, "description": "  中型服务  "},
            )
        )

    row = payload["data"]
    assert (row["cpu_millicores"], row["memory_mb"], row["description"]) == (1500, 3072, "中型服务")
    assert row["code"] == "standard" and row["enabled"] is True

    # And the table agrees — the answer is re-read, not echoed.
    from bisheng.database.models.resource_tier import ResourceTierDao

    async with publish_db() as session:
        stored = await ResourceTierDao.aget_by_code(session, "standard")
    assert (stored.cpu_millicores, stored.memory_mb) == (1500, 3072)

    audits = [call for call in audit_sink if call["action"] == AppAuditAction.TIER_UPDATE.value]
    assert len(audits) == 1
    audit = audits[0]
    assert audit["operator_id"] == super_admin_user.user_id
    assert audit["target_type"] == "resource_tier" and audit["target_id"] == "standard"
    assert audit["reason"] == "retuned"
    assert audit["metadata"]["changes"]["cpu_millicores"] == {"from": 2000, "to": 1500}
    assert audit["metadata"]["changes"]["memory_mb"] == {"from": 4096, "to": 3072}
    assert "description" in audit["metadata"]["changes"]


async def test_patch_with_no_effective_change_writes_no_audit(
    publish_db, api_app, tier_seed, super_admin_user, audit_sink
):
    """Re-saving the same numbers is not an event."""
    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/standard", json={"cpu_millicores": 2000, "memory_mb": 4096}))
    assert payload["status_code"] == 200
    assert audit_sink == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"cpu_millicores": 0}, "cpu_millicores"),
        ({"cpu_millicores": -500}, "cpu_millicores"),
        ({"memory_mb": 0}, "memory_mb"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 65}, "name"),
        ({"description": "x" * 501}, "description"),
    ],
)
async def test_patch_rejects_invalid_spec_16262_naming_the_field(
    publish_db, api_app, tier_seed, super_admin_user, audit_sink, body, field
):
    from bisheng.database.models.resource_tier import ResourceTierDao

    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/standard", json=body))
    assert payload["status_code"] == 16262, payload
    assert payload["data"]["details"]["field"] == field

    async with publish_db() as session:
        stored = await ResourceTierDao.aget_by_code(session, "standard")
    assert (stored.cpu_millicores, stored.memory_mb, stored.name) == (2000, 4096, "标准"), "nothing was written"
    assert audit_sink == []


async def test_patch_unknown_tier_16261(publish_db, api_app, tier_seed, super_admin_user):
    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/gigantic", json={"cpu_millicores": 1}))
    assert payload["status_code"] == 16261, payload


async def test_patch_cannot_rename_code(publish_db, api_app, tier_seed, super_admin_user):
    """``code`` is not part of the body; sending it changes nothing (renaming would dangle frozen tier_ids)."""
    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/standard", json={"code": "renamed"}))
    assert payload["status_code"] == 200
    assert payload["data"]["code"] == "standard"
    assert {row["code"] for row in (await _list(api_app, super_admin_user))} == {"light", "standard", "performance"}


async def _list(api_app, who):
    async with api_app(payload=who.payload) as client:
        return _body(await client.get(LIST_URL))["data"]


# ---------------------------------------------------------------------------
# AC-47 — disable keeps existing apps
# ---------------------------------------------------------------------------


async def test_disable_blocks_new_selection_but_existing_apps_keep_resolving(
    publish_db, api_app, tier_seed, super_admin_user, app_factory, audit_sink
):
    from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService
    from bisheng.app_runtime.domain.constants import AppAuditAction
    from bisheng.common.errcode.app_publish import AppTierUnavailableError

    _app, version = await app_factory(tier_id="performance", terminal_state="online")

    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/performance", json={"enabled": False}))
    assert payload["data"]["enabled"] is False
    assert payload["data"]["in_use_app_count"] == 1, "the app on it is still on it"

    # New publishes can no longer choose it …
    with pytest.raises(AppTierUnavailableError) as excinfo:
        await ResourceTierService.resolve_tier("performance")
    assert excinfo.value.kwargs["details"]["reason"] == "disabled"
    assert "performance" not in {t.code for t in await ResourceTierService.list_tiers(enabled_only=True)}

    # … but the frozen snapshot still resolves its spec (F054 relies on this).
    spec = await ResourceTierService.resolve_spec(version.tier_id)
    assert (spec.cpu_millicores, spec.memory_mb) == (4000, 8192)

    # The admin list still shows the retired tier, and the audit says "disabled".
    rows = await _list(api_app, super_admin_user)
    assert {row["code"]: row["enabled"] for row in rows} == {"light": True, "standard": True, "performance": False}
    audits = [call for call in audit_sink if call["action"] == AppAuditAction.TIER_UPDATE.value]
    assert [audit["reason"] for audit in audits] == ["disabled"]
    assert audits[0]["metadata"]["changes"] == {"enabled": {"from": True, "to": False}}

    # Re-enabling is the same endpoint, audited the other way round.
    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/performance", json={"enabled": True}))
    assert payload["data"]["enabled"] is True
    assert [audit["reason"] for audit in audit_sink if audit["action"] == AppAuditAction.TIER_UPDATE.value] == [
        "disabled",
        "enabled",
    ]


async def test_default_tier_cannot_be_disabled_16263(publish_db, api_app, tier_seed, super_admin_user, audit_sink):
    """AC-46 makes ``light`` the answer for every manifest without ``tier:``; retiring it would break them all."""
    from bisheng.database.models.resource_tier import DEFAULT_TIER_CODE, ResourceTierDao

    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/{DEFAULT_TIER_CODE}", json={"enabled": False}))
    assert payload["status_code"] == 16263, payload

    async with publish_db() as session:
        stored = await ResourceTierDao.aget_by_code(session, DEFAULT_TIER_CODE)
    assert stored.enabled is True
    assert audit_sink == []

    # Retuning the default tier is still fine — only retirement is refused.
    async with api_app(payload=super_admin_user.payload) as client:
        payload = _body(await client.patch(f"{LIST_URL}/{DEFAULT_TIER_CODE}", json={"cpu_millicores": 250}))
    assert payload["status_code"] == 200 and payload["data"]["cpu_millicores"] == 250


async def test_audit_action_is_registered_in_the_lockstep_whitelist():
    """Written events must be findable on the audit page (pit 21 / 24)."""
    from bisheng.app_runtime.domain.constants import AppAuditAction
    from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS

    assert AppAuditAction.TIER_UPDATE.value in _UI_VISIBLE_V2_ACTIONS
