from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_scenario_admin_service import (
    ApprovalScenarioAdminService,
)
from bisheng.common.errcode.approval import ApprovalFixedScenarioStructureLockedError

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f068_department_file_view_scenario_seed"


def _create_approval_config_tables(engine) -> None:
    for table in (
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
    ):
        table.create(engine)


def test_fixed_scenario_seed_is_idempotent_and_preserves_enabled() -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")
    _create_approval_config_tables(engine)

    with engine.begin() as connection:
        migration._ensure_seed(connection)
        scenario = (
            connection.execute(
                sa.select(ApprovalScenario.__table__).where(ApprovalScenario.scenario_code == migration.SCENARIO_CODE)
            )
            .mappings()
            .one()
        )
        connection.execute(
            sa.update(ApprovalScenario.__table__).where(ApprovalScenario.id == scenario["id"]).values(enabled=False)
        )
        migration._ensure_seed(connection)

        scenario_count = connection.scalar(sa.select(sa.func.count()).select_from(ApprovalScenario.__table__))
        route_count = connection.scalar(sa.select(sa.func.count()).select_from(ApprovalRouteRule.__table__))
        flow_count = connection.scalar(sa.select(sa.func.count()).select_from(ApprovalFlowDefinition.__table__))
        version_count = connection.scalar(sa.select(sa.func.count()).select_from(ApprovalFlowVersion.__table__))
        node_count = connection.scalar(sa.select(sa.func.count()).select_from(ApprovalNodeDefinition.__table__))
        enabled = connection.scalar(
            sa.select(ApprovalScenario.enabled).where(ApprovalScenario.scenario_code == migration.SCENARIO_CODE)
        )

    assert (scenario_count, route_count, flow_count, version_count, node_count) == (
        1,
        1,
        1,
        1,
        1,
    )
    assert enabled is False


def test_fixed_scenario_data_migration_upgrade_downgrade_upgrade() -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")
    _create_approval_config_tables(engine)

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with patch.object(migration, "op", operations):
            migration.upgrade()
            assert connection.scalar(sa.select(sa.func.count()).select_from(ApprovalScenario.__table__)) == 1

            migration.downgrade()
            assert connection.scalar(sa.select(sa.func.count()).select_from(ApprovalScenario.__table__)) == 0

            migration.upgrade()
            assert connection.scalar(sa.select(sa.func.count()).select_from(ApprovalScenario.__table__)) == 1


def test_registry_exposes_fixed_department_file_view_preset() -> None:
    preset = ApprovalRegistry.with_default_presets().get_preset("department_file_view_request")

    assert preset is not None
    assert preset.handler_key == "department_file_view_request"
    assert preset.approver_source_types == ["department_file_approvers"]


@pytest.mark.asyncio
async def test_fixed_scenario_list_flags_and_enabled_only_update() -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
        scenario_name="部门文件查看审批",
        enabled=True,
        display_name="部门文件查看审批",
        model_dump=lambda: {
            "id": 1,
            "tenant_id": 1,
            "scenario_code": "department_file_view_request",
            "scenario_name": "部门文件查看审批",
            "enabled": True,
        },
    )
    updated = SimpleNamespace(**scenario.model_dump(), model_dump=scenario.model_dump)

    with (
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service."
            "ApprovalScenarioRepository.list_scenarios",
            new=AsyncMock(return_value=[scenario]),
        ),
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service."
            "ApprovalScenarioRepository.update_scenario",
            new=AsyncMock(return_value=updated),
        ) as update_scenario,
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service.AuditLogDao.ainsert_v2",
            new=AsyncMock(),
        ),
    ):
        listed = await ApprovalScenarioAdminService.list_scenarios(tenant_id=1)
        await ApprovalScenarioAdminService.update_scenario(
            tenant_id=1,
            scenario_id=1,
            payload={"enabled": False, "toggle_reason": "维护"},
        )

    assert listed[0]["system_managed"] is True
    assert listed[0]["structure_locked"] is True
    update_scenario.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("create_route", {"scenario_id": 1, "payload": {"route_name": "x", "route_type": "approval"}}),
        ("create_flow", {"scenario_id": 1, "payload": {"flow_name": "x"}}),
        ("delete_scenario", {"scenario_id": 1}),
        ("reorder_routes", {"scenario_id": 1, "ordered_route_ids": []}),
    ],
)
async def test_fixed_scenario_rejects_structure_mutations(method: str, kwargs: dict) -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
    )
    with patch(
        "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
        new=AsyncMock(return_value=scenario),
    ):
        with pytest.raises(ApprovalFixedScenarioStructureLockedError):
            await getattr(ApprovalScenarioAdminService, method)(
                tenant_id=1,
                **kwargs,
            )


@pytest.mark.asyncio
async def test_fixed_scenario_rejects_non_enabled_field_update() -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
    )
    with patch(
        "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
        new=AsyncMock(return_value=scenario),
    ):
        with pytest.raises(ApprovalFixedScenarioStructureLockedError):
            await ApprovalScenarioAdminService.update_scenario(
                tenant_id=1,
                scenario_id=1,
                payload={"scenario_name": "篡改"},
            )
