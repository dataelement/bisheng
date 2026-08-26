"""Compose canonical business predicates for F048 system-owned resources."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlmodel import select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.process_runtime import get_f048_process_runtime
from bisheng.permission.application.system_resource_reconcile import (
    SYSTEM_RESOURCE_BOOTSTRAP_OPERATOR_ID,
    SystemOwnedReconcileReport,
    SystemOwnedResourceSpec,
    reconcile_system_owned_resources,
)
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.tool.domain.services.f048_tool_permission import SYSTEM_TOOL_ACTIONS


@dataclass(frozen=True, slots=True)
class InvalidSystemOwnedResource:
    resource_type: str
    resource_id: str
    reason: str

    @property
    def object_key(self) -> str:
        return f"{self.resource_type}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class SystemOwnedResourceInventory:
    resources: tuple[SystemOwnedResourceSpec, ...]
    invalid: tuple[InvalidSystemOwnedResource, ...]


def _context_version(*parts: object) -> str:
    return sha256("|".join(str(part) for part in parts).encode()).hexdigest()


async def load_system_owned_resource_inventory() -> SystemOwnedResourceInventory:
    """Load preset tool categories satisfying the strict system predicate."""

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            tool_types = (
                await session.exec(
                    select(GptsToolsType)
                    .where(
                        GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                        GptsToolsType.is_delete == 0,
                    )
                    .order_by(GptsToolsType.tenant_id, GptsToolsType.id)
                )
            ).all()
    resources: list[SystemOwnedResourceSpec] = []
    invalid: list[InvalidSystemOwnedResource] = []
    for row in tool_types:
        if row.id is None or not row.tenant_id:
            invalid.append(InvalidSystemOwnedResource("tool", str(row.id or ""), "missing tenant or resource identity"))
            continue
        if row.user_id is not None:
            invalid.append(InvalidSystemOwnedResource("tool", str(row.id), "preset tool category has a user owner"))
            continue
        resources.append(
            SystemOwnedResourceSpec(
                tenant_id=int(row.tenant_id),
                resource_type="tool",
                resource_id=str(row.id),
                action_codes=tuple(sorted(SYSTEM_TOOL_ACTIONS)),
                context_version=_context_version(
                    "tool",
                    row.id,
                    row.tenant_id,
                    row.user_id,
                    row.is_preset,
                    row.update_time.isoformat() if row.update_time else "0",
                ),
            )
        )
    return SystemOwnedResourceInventory(
        resources=tuple(resources),
        invalid=tuple(invalid),
    )


async def reconcile_fresh_install_system_resources() -> SystemOwnedReconcileReport:
    """Project system-owned rows created by the fresh-install data seeder."""

    process_runtime = await get_f048_process_runtime()
    components = process_runtime.components
    await components.marker.wait_until_ready(
        timeout_seconds=float(settings.openfga.recent_consistency_window_seconds) + 5.0,
    )
    inventory = await load_system_owned_resource_inventory()
    if inventory.invalid:
        details = ", ".join(f"{item.object_key} ({item.reason})" for item in inventory.invalid)
        raise PermissionPublishNotReadyError(msg=f"Invalid system-owned resource seed data: {details}")
    return await reconcile_system_owned_resources(
        components.facade,
        inventory.resources,
        apply=True,
        operator_id=SYSTEM_RESOURCE_BOOTSTRAP_OPERATOR_ID,
    )
