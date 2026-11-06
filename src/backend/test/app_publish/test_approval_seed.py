"""T026 — the "应用发布" approval scenario ships with the platform (AC-12 / AC-19 / AC-20).

The approval gate fails closed: with no ``approval_scenario`` row for
``(tenant_id, 'app_publish_request')`` the very first ``bisheng deploy`` raises
``ApprovalScenarioDisabledError``. So the seed is not setup convenience — it is
the difference between the demo path working and it stopping on step one.

What this file pins:

* **Shape.** One catch-all route (``match_config={}``) into one OR-mode node
  with ``department_admin`` then ``tenant_admin``. Asserted field by field
  because each of the five rows has a flag that silently disables the flow when
  wrong (``enabled`` / ``is_active`` / ``node_order`` / ``route_type``).
* **Idempotence keyed on ``(tenant_id, scenario_code)``** — which *is* AC-19.
  An operator who reconfigures the flow must not have it reset by the next
  upgrade, so a second seed pass has to skip the whole bundle, not just the
  scenario row.
* **Both tenant-creation paths.** ``TenantService.acreate_tenant`` (the admin
  console) and ``TenantMountService.mount_child`` (department → child tenant).
  Wiring only one leaves a hole that surfaces the day a customer creates their
  second tenant (design 坑 3), so both are asserted — structurally, since
  running either end to end would need OpenFGA, the workstation service and the
  audit pipeline, none of which say anything about seeding.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from sqlmodel import select

from .conftest import ROOT_TENANT_ID, SUB_TENANT_ID

pytestmark = pytest.mark.asyncio

APP_PUBLISH_SCENARIO = "app_publish_request"


def _seeds():
    from bisheng.approval.domain.services.approval_seed_service import DEFAULT_APPROVAL_SCENARIO_SEEDS

    return DEFAULT_APPROVAL_SCENARIO_SEEDS


async def _seed(publish_db, tenant_id: int = ROOT_TENANT_ID) -> None:
    from bisheng.approval.domain.services.approval_seed_service import seed_approval_scenarios_in_session

    async with publish_db() as session:
        await seed_approval_scenarios_in_session(session, tenant_id)
        await session.commit()


async def _scenario(publish_db, tenant_id: int, code: str = APP_PUBLISH_SCENARIO):
    from bisheng.approval.domain.models.approval_scenario import ApprovalScenario

    async with publish_db() as session:
        rows = (
            await session.exec(
                select(ApprovalScenario).where(
                    ApprovalScenario.tenant_id == tenant_id,
                    ApprovalScenario.scenario_code == code,
                )
            )
        ).all()
    return list(rows)


# ---------------------------------------------------------------------------
# AC-12 — it exists, enabled, on a fresh deployment
# ---------------------------------------------------------------------------


async def test_fresh_deploy_has_app_publish_scenario_enabled(publish_db):
    await _seed(publish_db)

    rows = await _scenario(publish_db, ROOT_TENANT_ID)

    assert len(rows) == 1
    assert rows[0].enabled is True
    assert rows[0].scenario_name == "应用发布"


async def test_seed_shape_single_catchall_route_single_or_node(publish_db):
    """Five rows, and every flag that could silently disable the flow."""
    from bisheng.approval.domain.models.approval_scenario import (
        ApprovalFlowDefinition,
        ApprovalFlowVersion,
        ApprovalNodeDefinition,
        ApprovalRouteRule,
    )

    await _seed(publish_db)
    scenario = (await _scenario(publish_db, ROOT_TENANT_ID))[0]

    async with publish_db() as session:
        routes = list(
            (await session.exec(select(ApprovalRouteRule).where(ApprovalRouteRule.scenario_id == scenario.id))).all()
        )
        flows = list(
            (
                await session.exec(
                    select(ApprovalFlowDefinition).where(ApprovalFlowDefinition.scenario_id == scenario.id)
                )
            ).all()
        )
        versions = list(
            (
                await session.exec(
                    select(ApprovalFlowVersion).where(ApprovalFlowVersion.flow_definition_id == flows[0].id)
                )
            ).all()
        )
        nodes = list(
            (
                await session.exec(
                    select(ApprovalNodeDefinition).where(ApprovalNodeDefinition.flow_version_id == versions[0].id)
                )
            ).all()
        )

    assert len(routes) == 1
    # An empty match_config is what makes it a catch-all: the gate's route
    # matcher returns the first enabled route whose config carries no "field".
    assert routes[0].match_config == {}
    assert routes[0].route_type == "flow"
    assert routes[0].enabled is True
    assert routes[0].flow_definition_id == flows[0].id

    assert len(flows) == 1 and flows[0].is_active is True
    assert len(versions) == 1 and versions[0].version_no == 1 and versions[0].is_active is True
    assert len(nodes) == 1 and nodes[0].node_order == 1 and nodes[0].node_mode == "or"


async def test_sources_are_department_admin_and_tenant_admin(publish_db):
    """Order matters only for readability, membership matters for AC-14."""
    from bisheng.approval.domain.models.approval_scenario import ApprovalNodeDefinition

    await _seed(publish_db)
    async with publish_db() as session:
        nodes = list((await session.exec(select(ApprovalNodeDefinition))).all())

    node = next(one for one in nodes if one.node_code == "app_publish_admin")
    assert node.approver_config == {"sources": [{"type": "department_admin"}, {"type": "tenant_admin"}]}


async def test_scenario_is_seeded_per_tenant(publish_db):
    """Two tenants, two independent scenario rows — the tenant is a parameter, not a constant."""
    await _seed(publish_db, ROOT_TENANT_ID)
    await _seed(publish_db, SUB_TENANT_ID)

    assert len(await _scenario(publish_db, ROOT_TENANT_ID)) == 1
    assert len(await _scenario(publish_db, SUB_TENANT_ID)) == 1


# ---------------------------------------------------------------------------
# AC-19 — an upgrade must not reset an operator's configuration
# ---------------------------------------------------------------------------


async def test_seed_idempotent_by_tenant_and_scenario_code(publish_db):
    from bisheng.approval.domain.models.approval_scenario import ApprovalFlowDefinition, ApprovalRouteRule

    await _seed(publish_db)
    await _seed(publish_db)

    assert len(await _scenario(publish_db, ROOT_TENANT_ID)) == 1
    async with publish_db() as session:
        flows = list((await session.exec(select(ApprovalFlowDefinition))).all())
        routes = list((await session.exec(select(ApprovalRouteRule))).all())
    assert len(flows) == len(_seeds())
    assert len(routes) == len(_seeds())


async def test_manual_reconfig_survives_reseed(publish_db):
    """Reshaped approvers stay reshaped. This is the whole of AC-19."""
    from bisheng.approval.domain.models.approval_scenario import ApprovalNodeDefinition, ApprovalScenario

    await _seed(publish_db)
    async with publish_db() as session:
        scenario = (
            await session.exec(select(ApprovalScenario).where(ApprovalScenario.scenario_code == APP_PUBLISH_SCENARIO))
        ).first()
        scenario.scenario_name = "应用发布（自定义）"
        node = (
            await session.exec(
                select(ApprovalNodeDefinition).where(ApprovalNodeDefinition.node_code == "app_publish_admin")
            )
        ).first()
        node.approver_config = {"sources": [{"type": "direct_user", "user_ids": [9]}]}
        session.add(scenario)
        session.add(node)
        await session.commit()

    await _seed(publish_db)

    async with publish_db() as session:
        scenario = (
            await session.exec(select(ApprovalScenario).where(ApprovalScenario.scenario_code == APP_PUBLISH_SCENARIO))
        ).first()
        nodes = list(
            (
                await session.exec(
                    select(ApprovalNodeDefinition).where(ApprovalNodeDefinition.node_code == "app_publish_admin")
                )
            ).all()
        )
    assert scenario.scenario_name == "应用发布（自定义）"
    assert len(nodes) == 1
    assert nodes[0].approver_config == {"sources": [{"type": "direct_user", "user_ids": [9]}]}


async def test_menu_access_scenario_not_touched(publish_db):
    """``menu_access_request`` stays unseeded — enabling it is a product decision, not a seed change."""
    from bisheng.approval.domain.models.approval_scenario import ApprovalScenario

    await _seed(publish_db)

    assert all(seed["scenario_code"] != "menu_access_request" for seed in _seeds())
    async with publish_db() as session:
        rows = list(
            (
                await session.exec(
                    select(ApprovalScenario).where(ApprovalScenario.scenario_code == "menu_access_request")
                )
            ).all()
        )
    assert rows == []


async def test_existing_two_scenarios_still_seeded(publish_db):
    """The two shipped scenarios are untouched by the addition of the third."""
    await _seed(publish_db)

    codes = {seed["scenario_code"] for seed in _seeds()}
    assert {"channel_subscribe_request", "knowledge_space_subscribe_request", APP_PUBLISH_SCENARIO} == codes
    assert len(await _scenario(publish_db, ROOT_TENANT_ID, "channel_subscribe_request")) == 1
    assert len(await _scenario(publish_db, ROOT_TENANT_ID, "knowledge_space_subscribe_request")) == 1


async def test_boot_path_still_seeds_the_default_tenant(publish_db):
    """``init_data`` keeps its old one-argument call and still targets the default tenant."""
    from bisheng.common.init_data import _init_default_approval_scenarios

    async with publish_db() as session:
        await _init_default_approval_scenarios(session)
        await session.commit()

    assert len(await _scenario(publish_db, ROOT_TENANT_ID)) == 1


# ---------------------------------------------------------------------------
# AC-20 — both tenant-creation paths
# ---------------------------------------------------------------------------


async def test_tenant_scoped_entry_point_seeds_an_arbitrary_tenant(publish_db):
    """``seed_approval_scenarios_for_tenant`` owns its session — that is what the hooks call."""
    from bisheng.approval.domain.services.approval_seed_service import seed_approval_scenarios_for_tenant

    await seed_approval_scenarios_for_tenant(SUB_TENANT_ID + 3)

    assert len(await _scenario(publish_db, SUB_TENANT_ID + 3)) == 1


def _seed_call_nodes(func):
    """Every ``seed_approval_scenarios_for_tenant(...)`` call inside ``func``, with its ancestors.

    Structural rather than behavioural on purpose: driving either creation path
    end to end needs OpenFGA, the workstation service, the department tree and
    the audit pipeline — none of which have anything to say about whether the
    seed hook is present. What must never regress is "the call is there, and it
    cannot take tenant creation down with it", and that is exactly what the AST
    shows.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "seed_approval_scenarios_for_tenant":
            ancestors = []
            cursor = node
            while cursor in parents:
                cursor = parents[cursor]
                ancestors.append(cursor)
            found.append(ancestors)
    return found


async def test_create_tenant_path_seeds_scenario():
    """``TenantService.acreate_tenant`` — the admin-console path, and the one both upstream docs omit."""
    from bisheng.tenant.domain.services.tenant_service import TenantService

    calls = _seed_call_nodes(TenantService.acreate_tenant)

    assert len(calls) == 1, "acreate_tenant must seed approval scenarios exactly once"


async def test_mount_child_path_seeds_scenario():
    """``TenantMountService.mount_child`` — department mounted as a child tenant."""
    from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

    calls = _seed_call_nodes(TenantMountService.mount_child)

    assert len(calls) == 1, "mount_child must seed approval scenarios exactly once"


async def test_seed_failure_does_not_break_tenant_creation():
    """Both hooks sit inside a ``try``: an unseeded scenario is recoverable, a half-created tenant is not."""
    from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
    from bisheng.tenant.domain.services.tenant_service import TenantService

    for func in (TenantService.acreate_tenant, TenantMountService.mount_child):
        for ancestors in _seed_call_nodes(func):
            assert any(isinstance(one, ast.Try) for one in ancestors), (
                f"{func.__qualname__} calls the approval seed outside a try/except; a seeding failure "
                "would then abort tenant creation"
            )
