"""T024 — the ``tenant_admin`` approver source, corrected (AC-15 / AC-21).

This suite guards a **behaviour change to existing code**, not a new feature.
Before it, ``approver_resolver``'s ``tenant_admin`` branch resolved
``UserRoleDao.aget_roles_user([AdminRole])`` — every platform super admin, for
every tenant, ignoring ``req.tenant_id`` entirely (its own comment called that
a "pragmatic approximation"). Every scenario and every hand-configured node
that names ``tenant_admin`` changes behaviour the moment that branch is fixed,
so half of this file is regression cover for the two scenarios that already
ship.

The three things it pins down:

* **Resolution is per tenant.** A child tenant's approvals go to that tenant's
  administrators, never to the platform super admins.
* **Root, and only Root, falls back.** ``TenantAdminService.list_tenant_admins``
  returns ``[]`` for Root *by design* (INV-T3), so a single-tenant deployment
  would resolve nobody without the fallback. A non-Root tenant with no
  administrator resolves nobody — that is an ``approver_empty`` exception an
  administrator can act on, not a reason to widen who may approve.
* **The notification-side function is untouched.** ``_get_admin_recipient_ids``
  is an *unconditional union* of super admins and tenant admins and must stay
  that way: it picks recipients of an approval-exception notice, where one
  extra reader is harmless. Merging it with approver resolution in either
  direction breaks the other's contract (design 坑 2).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import ROOT_TENANT_ID, SUB_TENANT_ID, SUPER_ADMIN_USER_ID, TENANT_ADMIN_USER_ID

pytestmark = pytest.mark.asyncio


def _req(tenant_id: int, *, department_id: int | None = None, applicant_user_id: int = 1):
    """The subset of ``ApprovalGateRequest`` the resolver reads.

    A namespace rather than the pydantic model because the engine itself hands
    the resolver a ``SimpleNamespace`` when it advances to a second node
    (``approval_center_service._advance_after_node_approved``) — the resolver
    must keep working against both shapes.
    """
    return SimpleNamespace(
        tenant_id=tenant_id,
        applicant_user_id=applicant_user_id,
        applicant_department_id=department_id,
        payload_snapshot={},
        business_resource_id="",
        business_resource_type="",
    )


async def _resolve(sources, req):
    from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources

    return await resolve_approvers_from_sources(sources, req)


# ---------------------------------------------------------------------------
# AC-21 — per-tenant resolution
# ---------------------------------------------------------------------------


async def test_tenant_admin_source_resolves_real_tenant_admins_not_super_admin(
    publish_db, tenant_admin_user, super_admin_user
):
    """The child tenant's administrator, and *not* the platform super admin.

    Both users exist here on purpose: the old implementation returned the super
    admin and ignored the tenant, so a test that seeded only one of them would
    pass against either version.
    """
    resolved = await _resolve([{"type": "tenant_admin"}], _req(SUB_TENANT_ID))

    assert resolved == [TENANT_ADMIN_USER_ID]
    assert SUPER_ADMIN_USER_ID not in resolved


async def test_sub_tenant_admin_only_sees_own_tenant_approvals(publish_db, tenant_admin_user, super_admin_user):
    """A tenant with no administrator of its own resolves nobody — it does not inherit another tenant's."""
    other_tenant = SUB_TENANT_ID + 7

    assert await _resolve([{"type": "tenant_admin"}], _req(other_tenant)) == []


# ---------------------------------------------------------------------------
# AC-15 — the Root fallback, and its exact boundary
# ---------------------------------------------------------------------------


async def test_root_tenant_falls_back_to_super_admin(publish_db, tenant_admin_user, super_admin_user):
    """Root has no tenant administrators by construction, so it resolves the platform super admins.

    114 is a single-tenant deployment, which means the demo path takes this
    branch every single time — it is the common case, not an edge case.
    """
    resolved = await _resolve([{"type": "tenant_admin"}], _req(ROOT_TENANT_ID))

    assert resolved == [SUPER_ADMIN_USER_ID]


async def test_non_root_tenant_with_no_admin_does_not_fallback(publish_db, tenant_admin_user, super_admin_user):
    """No administrator on a child tenant → empty, which becomes ``approver_empty``.

    Falling back here would reintroduce exactly the defect AC-21 removes: every
    tenant's approvals landing on the super admins.
    """
    empty_tenant = SUB_TENANT_ID + 11
    department_only = [{"type": "department_admin"}, {"type": "tenant_admin"}]

    assert await _resolve(department_only, _req(empty_tenant)) == []


async def test_root_fallback_is_skipped_when_root_somehow_has_admins(publish_db, monkeypatch, super_admin_user):
    """The fallback is a fallback: real administrators win even on Root.

    Pins the branch order. Written the other way round ("Root always means
    super admins") the function would ignore a future Root-admin grant without
    anybody noticing.
    """
    from bisheng.tenant.domain.services.tenant_admin_service import TenantAdminService

    async def _list(cls, tenant_id: int) -> list[int]:
        return [77001]

    monkeypatch.setattr(TenantAdminService, "list_tenant_admins", classmethod(_list))

    assert await _resolve([{"type": "tenant_admin"}], _req(ROOT_TENANT_ID)) == [77001]


async def test_permission_backend_failure_resolves_empty_not_super_admin(publish_db, monkeypatch, super_admin_user):
    """A permission backend outage fails closed on a child tenant.

    ``list_tenant_admins`` already swallows its own errors and returns ``[]``;
    the fallback must not turn that into "everybody with AdminRole may approve".
    """
    from bisheng.tenant.domain.services.tenant_admin_service import TenantAdminService

    async def _boom(cls, tenant_id: int) -> list[int]:
        raise RuntimeError("openfga unreachable")

    monkeypatch.setattr(TenantAdminService, "list_tenant_admins", classmethod(_boom))

    assert await _resolve([{"type": "tenant_admin"}], _req(SUB_TENANT_ID)) == []


# ---------------------------------------------------------------------------
# AC-21 — regression cover for the scenarios that already ship
# ---------------------------------------------------------------------------


async def test_existing_channel_scenario_still_resolves_approvers(publish_db, tenant_admin_user, dept_admin_user):
    """Channel subscription: its own sources are untouched and generic ones still route through the resolver."""
    from bisheng.approval.domain.services.channel_subscribe_scenario_handler import ChannelSubscribeScenarioHandler

    class _Membership:
        async def find_membership(self, *args, **kwargs):
            return None

        async def update(self, membership):
            return membership

        async def delete(self, membership_id: int) -> bool:
            return True

    handler = ChannelSubscribeScenarioHandler(_Membership())
    node_config = {"sources": [{"type": "department_admin"}, {"type": "tenant_admin"}]}
    req = _req(SUB_TENANT_ID, department_id=dept_admin_user.department_id)

    resolved = await handler.resolve_approvers(node_config, req)

    assert dept_admin_user.user_id in resolved
    assert TENANT_ADMIN_USER_ID in resolved


async def test_existing_knowledge_space_scenario_still_resolves_approvers(
    publish_db, tenant_admin_user, dept_admin_user
):
    """Knowledge-space join: same guard, through the other shipped handler."""
    from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
        KnowledgeSpaceSubscribeScenarioHandler,
    )

    async def _noop(*args, **kwargs):
        return None

    handler = KnowledgeSpaceSubscribeScenarioHandler(find_member=_noop, update_member=_noop, sync_permissions=_noop)
    node_config = {"sources": [{"type": "department_admin"}, {"type": "tenant_admin"}]}
    req = _req(SUB_TENANT_ID, department_id=dept_admin_user.department_id)

    resolved = await handler.resolve_approvers(node_config, req)

    assert dept_admin_user.user_id in resolved
    assert TENANT_ADMIN_USER_ID in resolved


async def test_direct_user_and_department_admin_sources_unchanged(publish_db, dept_admin_user):
    """The other two generic sources keep their exact behaviour and ordering."""
    sources = [{"type": "direct_user", "user_ids": [4242]}, {"type": "department_admin"}]

    resolved = await _resolve(sources, _req(ROOT_TENANT_ID, department_id=dept_admin_user.department_id))

    assert resolved == [4242, dept_admin_user.user_id]


# ---------------------------------------------------------------------------
# AC-21 — the function that must NOT have been merged with the above
# ---------------------------------------------------------------------------


async def test_notification_recipient_function_unchanged(publish_db, tenant_admin_user, super_admin_user):
    """``_get_admin_recipient_ids`` stays an unconditional union.

    Asserted behaviourally rather than by reading the source: for a **child**
    tenant it must return the super admin *and* the tenant administrator. A
    conditional fallback (what approver resolution needs) would drop the super
    admin here and silently change who gets told about approval exceptions.
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    recipients = await ApprovalNotificationService._get_admin_recipient_ids(tenant_id=SUB_TENANT_ID)

    assert SUPER_ADMIN_USER_ID in recipients
    assert TENANT_ADMIN_USER_ID in recipients


async def test_notification_recipients_still_include_super_admin_for_root(publish_db, super_admin_user):
    """Root: the notification side reaches super admins through the union, not through a fallback."""
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    recipients = await ApprovalNotificationService._get_admin_recipient_ids(tenant_id=ROOT_TENANT_ID)

    assert recipients == [SUPER_ADMIN_USER_ID]


async def test_unknown_source_type_is_still_skipped(publish_db):
    """Unknown types stay a warning-and-skip; the fix did not turn them into failures."""
    assert await _resolve([{"type": "no_such_source"}], _req(ROOT_TENANT_ID)) == []
