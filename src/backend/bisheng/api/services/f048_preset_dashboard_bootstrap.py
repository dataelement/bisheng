"""Project the two seeded dashboard examples as ordinary user-owned resources."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlmodel import col, select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.permission.application.process_runtime import get_f048_process_runtime
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.telemetry_search.domain.models.dashboard import Dashboard, DashboardType
from bisheng.telemetry_search.domain.services.f048_dashboard_permission import (
    VALID_DASHBOARD_STATUSES,
)
from bisheng.user.domain.models.user_role import UserRole

PRESET_DASHBOARD_IDS = (10, 11)
PRESET_DASHBOARD_OWNER_ID = 1
PRESET_DASHBOARD_TYPES = frozenset(
    {
        DashboardType.PRESET_OSS.value,
        DashboardType.PRESET_COMMERCIAL.value,
    }
)


@dataclass(frozen=True, slots=True)
class PresetDashboardProjectionReport:
    owner_ready: bool
    resource_count: int
    missing_count: int
    current_count: int


async def _owner_is_ready() -> bool:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            role = (
                await session.exec(
                    select(UserRole.id).where(
                        UserRole.user_id == PRESET_DASHBOARD_OWNER_ID,
                        UserRole.role_id == AdminRole,
                    )
                )
            ).first()
    return role is not None


async def _load_preset_dashboards_and_modes():
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            dashboards = (
                await session.exec(
                    select(Dashboard).where(col(Dashboard.id).in_(PRESET_DASHBOARD_IDS)).order_by(Dashboard.id)
                )
            ).all()
            modes = (
                await session.exec(
                    select(ResourcePermissionMode).where(
                        ResourcePermissionMode.tenant_id == DEFAULT_TENANT_ID,
                        ResourcePermissionMode.resource_type == "dashboard",
                        col(ResourcePermissionMode.resource_id).in_(tuple(str(item) for item in PRESET_DASHBOARD_IDS)),
                    )
                )
            ).all()
    return tuple(dashboards), {str(mode.resource_id): mode for mode in modes}


def _validate_dashboard(dashboard: Dashboard) -> None:
    if (
        dashboard.id not in PRESET_DASHBOARD_IDS
        or dashboard.tenant_id != DEFAULT_TENANT_ID
        or dashboard.user_id != PRESET_DASHBOARD_OWNER_ID
        or dashboard.dashboard_type not in PRESET_DASHBOARD_TYPES
        or dashboard.status not in VALID_DASHBOARD_STATUSES
    ):
        raise PermissionPublishNotReadyError(
            msg=f"Preset dashboard {dashboard.id} does not match its seeded owner facts"
        )


def _context_version(dashboard: Dashboard) -> str:
    updated = dashboard.update_time.isoformat() if dashboard.update_time else "0"
    value = (
        f"dashboard|{dashboard.id}|{dashboard.tenant_id}|{dashboard.user_id}|"
        f"{dashboard.dashboard_type}|{dashboard.status}|{updated}"
    )
    return sha256(value.encode()).hexdigest()


async def reconcile_preset_dashboard_permissions() -> PresetDashboardProjectionReport:
    """Create protected owner Grants after the first super admin exists."""

    dashboards, modes = await _load_preset_dashboards_and_modes()
    for dashboard in dashboards:
        _validate_dashboard(dashboard)
    non_current = tuple(mode for mode in modes.values() if mode.projection_state != "CURRENT")
    if non_current:
        resources = ", ".join(f"dashboard:{mode.resource_id}" for mode in non_current)
        raise PermissionPublishNotReadyError(
            msg=f"Preset dashboards have non-current permission projections: {resources}"
        )
    missing = tuple(dashboard for dashboard in dashboards if str(dashboard.id) not in modes)
    if not dashboards or not await _owner_is_ready():
        return PresetDashboardProjectionReport(
            owner_ready=False,
            resource_count=len(dashboards),
            missing_count=len(missing),
            current_count=len(modes),
        )
    if missing:
        process_runtime = await get_f048_process_runtime()
        components = process_runtime.components
        await components.marker.wait_until_ready(
            timeout_seconds=float(settings.openfga.recent_consistency_window_seconds) + 5.0,
        )
        actor = PermissionActor(
            user_id=PRESET_DASHBOARD_OWNER_ID,
            current_tenant_id=DEFAULT_TENANT_ID,
            super_admin=True,
        )
        for dashboard in missing:
            await components.facade.authorize_created(
                actor=actor,
                target=VerifiedPermissionTarget.from_business_service(
                    tenant_id=DEFAULT_TENANT_ID,
                    resource_type="dashboard",
                    resource_id=str(dashboard.id),
                    resource_version=0,
                    context_version=_context_version(dashboard),
                ),
                owner_user_id=PRESET_DASHBOARD_OWNER_ID,
                mode="CUSTOM",
                source_type="CREATOR",
                protected=True,
                idempotency_key=(f"f048:preset-dashboard-owner:{dashboard.id}:{PRESET_DASHBOARD_OWNER_ID}"),
            )
        _, modes = await _load_preset_dashboards_and_modes()
    if any(
        str(dashboard.id) not in modes or modes[str(dashboard.id)].projection_state != "CURRENT"
        for dashboard in dashboards
    ):
        raise PermissionPublishNotReadyError(msg="Preset dashboard owner projections did not finalize")
    return PresetDashboardProjectionReport(
        owner_ready=True,
        resource_count=len(dashboards),
        missing_count=len(missing),
        current_count=len(modes),
    )
