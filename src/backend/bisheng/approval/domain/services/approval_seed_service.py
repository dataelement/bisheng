"""Preset approval scenarios, seeded per tenant (F055 design D8 / AC-12 / AC-19 / AC-20).

The approval gate fails closed: no ``approval_scenario`` row for
``(tenant_id, scenario_code)`` means ``ApprovalScenarioDisabledError`` on the
very first request of that scenario. So "the scenario ships with the platform"
is not a convenience — for ``app_publish_request`` it is the difference between
``bisheng deploy`` working out of the box and it failing on step one.

Three properties this module exists to hold:

* **Tenant is a parameter, not a constant.** The seeding used to hardcode the
  default tenant in six places, which meant a tenant created after boot never
  got any scenario at all. Both tenant-creation paths now call
  :func:`seed_approval_scenarios_for_tenant`.
* **Idempotence is keyed on ``(tenant_id, scenario_code)``, and that key is the
  whole of AC-19.** An operator who reconfigures the flow — different
  approvers, an extra node — must not have it silently reset by the next
  platform upgrade. Existing scenario → skip the entire seed, including the
  flow, the node and the route.
* **The seed shape is the minimum that is still a legal flow**: one catch-all
  route (``match_config={}`` — the gate returns the first route with no
  ``field``) into a single OR-mode node. Anything richer is a product decision
  an operator makes in the admin UI, not something a default should presume.

Note the scenario / flow / node names are Chinese single-language, exactly like
the three presets in ``approval_registry``. The admin page renders
``scenario_name`` verbatim; making this one translatable while the others are
not would be a half-migration that reads as a bug in every non-Chinese locale.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlmodel import select

#: Scenarios every tenant gets. Each entry seeds five rows — see
#: :func:`seed_approval_scenarios_in_session`.
#:
#: ``menu_access_request`` is deliberately absent: it ships with the platform as
#: a *disabled* capability an operator turns on, and quietly enabling it here
#: would be a product change smuggled in as a seed change.
DEFAULT_APPROVAL_SCENARIO_SEEDS: list[dict[str, Any]] = [
    {
        "scenario_code": "channel_subscribe_request",
        "scenario_name": "频道订阅审批",
        "flow_code": "channel_subscribe_default_flow",
        "flow_name": "默认流程",
        "node_code": "channel_owner_manager",
        "node_name": "频道负责人审批",
        "sources": [{"type": "channel_owner"}, {"type": "channel_manager"}],
    },
    {
        "scenario_code": "knowledge_space_subscribe_request",
        "scenario_name": "知识空间加入审批",
        "flow_code": "knowledge_space_subscribe_default_flow",
        "flow_name": "默认流程",
        "node_code": "knowledge_space_owner_manager",
        "node_name": "知识空间负责人审批",
        "sources": [{"type": "knowledge_space_owner"}, {"type": "knowledge_space_manager"}],
    },
    {
        # F055 AC-12: hosted-application publishing. Department administrator
        # first, tenant administrator second — an OR node, so whoever gets to
        # it first decides. The owner's *primary* department supplies the first
        # source; an owner without one contributes nothing there and the whole
        # node falls to the tenant administrators (AC-14).
        "scenario_code": "app_publish_request",
        "scenario_name": "应用发布",
        "flow_code": "app_publish_default_flow",
        "flow_name": "默认流程",
        "node_code": "app_publish_admin",
        "node_name": "应用发布审批",
        "sources": [{"type": "department_admin"}, {"type": "tenant_admin"}],
    },
]


async def seed_approval_scenarios_in_session(session, tenant_id: int) -> None:
    """Seed every preset scenario for one tenant, reusing the caller's session.

    Runs inside ``bypass_tenant_filter`` because it writes rows *for* a tenant
    that is usually not the ambient one (a tenant being created, or the default
    tenant during boot). Each scenario commits on its own so a failure part-way
    through leaves the scenarios before it usable rather than rolling back the
    lot.
    """
    from bisheng.approval.domain.models.approval_scenario import (
        ApprovalFlowDefinition,
        ApprovalFlowVersion,
        ApprovalNodeDefinition,
        ApprovalRouteRule,
        ApprovalScenario,
    )
    from bisheng.core.context.tenant import bypass_tenant_filter

    tenant_id = int(tenant_id)
    with bypass_tenant_filter():
        for seed in DEFAULT_APPROVAL_SCENARIO_SEEDS:
            existing = (
                await session.exec(
                    select(ApprovalScenario).where(
                        ApprovalScenario.tenant_id == tenant_id,
                        ApprovalScenario.scenario_code == seed["scenario_code"],
                    )
                )
            ).first()
            if existing:
                # AC-19: the row exists, so an operator may have reshaped the
                # flow behind it. Skipping the whole seed — not just the
                # scenario row — is what keeps that reshaping across upgrades.
                continue

            scenario = ApprovalScenario(
                tenant_id=tenant_id,
                scenario_code=seed["scenario_code"],
                scenario_name=seed["scenario_name"],
                enabled=True,
            )
            session.add(scenario)
            await session.flush()
            await session.refresh(scenario)

            flow = ApprovalFlowDefinition(
                tenant_id=tenant_id,
                scenario_id=scenario.id,
                flow_code=seed["flow_code"],
                flow_name=seed["flow_name"],
                is_active=True,
            )
            session.add(flow)
            await session.flush()
            await session.refresh(flow)

            node_snapshot = {
                "node_code": seed["node_code"],
                "node_name": seed["node_name"],
                "node_order": 1,
                "node_mode": "or",
                "approver_config": {"sources": seed["sources"]},
            }
            version = ApprovalFlowVersion(
                tenant_id=tenant_id,
                flow_definition_id=flow.id,
                version_no=1,
                is_active=True,
                definition_snapshot={"nodes": [node_snapshot]},
            )
            session.add(version)
            await session.flush()
            await session.refresh(version)

            session.add(
                ApprovalNodeDefinition(
                    tenant_id=tenant_id,
                    flow_version_id=version.id,
                    node_code=seed["node_code"],
                    node_name=seed["node_name"],
                    node_order=1,
                    node_mode="or",
                    approver_config={"sources": seed["sources"]},
                )
            )
            session.add(
                ApprovalRouteRule(
                    tenant_id=tenant_id,
                    scenario_id=scenario.id,
                    route_name="默认分支",
                    route_type="flow",
                    sort_order=1,
                    flow_definition_id=flow.id,
                    # Catch-all: the gate's route matcher returns the first
                    # enabled route whose match_config carries no ``field``.
                    match_config={},
                    enabled=True,
                )
            )
            await session.commit()
            logger.info(f"Seeded approval scenario {seed['scenario_code']} (id={scenario.id}) for tenant {tenant_id}")


async def seed_approval_scenarios_for_tenant(tenant_id: int) -> None:
    """Public entry for a freshly created tenant. Opens and owns its session.

    Called from **both** tenant-creation paths (``TenantService.acreate_tenant``
    and ``TenantMountService.mount_child``). Boot-time seeding only covers the
    tenants that existed at boot, so a tenant created later has no scenario at
    all until this runs — and the symptom is a first ``deploy`` failing with
    "approval scenario not enabled", days after the tenant was created.
    """
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        await seed_approval_scenarios_in_session(session, tenant_id)
