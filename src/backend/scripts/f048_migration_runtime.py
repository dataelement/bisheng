"""Live dependency composition for the explicit F048 migration CLI.

This module belongs to the operational script layer so the permission domain
can consume business-owned migration ports without importing business ORM
models or repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bisheng.api.services.permission_migration_source import (
    ApplicationPermissionMigrationSource,
    SqlApplicationMigrationRepository,
)
from bisheng.channel.domain.services.permission_migration_source import (
    ChannelPermissionMigrationSource,
    SqlChannelMigrationRepository,
)
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.common.services.config_service import settings
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.discovery import discover_openfga_runtime
from bisheng.knowledge.domain.services.permission_migration_source import (
    KnowledgePermissionMigrationSource,
    SqlKnowledgeMigrationRepository,
)
from bisheng.permission.migration.f048_coordinator import (
    F048MigrationCoordinator,
)
from bisheng.permission.migration.f048_runtime_source import (
    LiveMigrationSourceProvider,
)
from bisheng.permission.migration.f048_runtime_storage import (
    OpenFGAMigrationModelPublisher,
    SqlMigrationRunStore,
    SqlOpenFGAMigrationTargetWriter,
)
from bisheng.permission.migration.f048_runtime_verification import (
    LiveMigrationEvidenceProvider,
)
from bisheng.permission.migration.f048_verifier import F048MigrationVerifier
from bisheng.telemetry_search.domain.services.permission_migration_source import (
    DashboardPermissionMigrationSource,
    SqlDashboardMigrationRepository,
)
from bisheng.tenant.domain.services.permission_migration_source import (
    LegacyIdentityPermissionMigrationSource,
)
from bisheng.tool.domain.services.permission_migration_source import (
    SqlToolMigrationRepository,
    ToolPermissionMigrationSource,
)


def _environment_name(value: str | dict[str, Any]) -> str:
    if isinstance(value, dict):
        value = next(
            (value[key] for key in ("name", "environment", "env", "mode") if value.get(key)),
            "dev",
        )
    return str(value or "dev")[:64]


@dataclass(slots=True)
class F048MigrationRuntime:
    coordinator: F048MigrationCoordinator
    verifier: F048MigrationVerifier
    source_client: FGAClient
    target_writer: SqlOpenFGAMigrationTargetWriter

    async def aclose(self) -> None:
        await self.target_writer.aclose()
        await self.source_client.close()


async def build_f048_migration_runtime(
    live_settings: Any = settings,
    *,
    run_id: int | None = None,
) -> F048MigrationRuntime:
    """Compose live SQL/OpenFGA/business adapters after app-context startup."""

    config = live_settings.openfga
    if not config.enabled:
        raise PermissionMigrationBlockedError(msg="OPENFGA_DISABLED")
    run_store = SqlMigrationRunStore()
    run = await run_store.aget_run(run_id) if run_id is not None else None
    if run_id is not None and run is None:
        raise PermissionMigrationBlockedError(msg="VERIFY_REQUIRES_EXISTING_FORMAL_RUN")
    pin = await discover_openfga_runtime(
        config,
        expected_model=None,
        allow_bootstrap=False,
        required_store_id=run.store_id if run else None,
        required_model_id=run.source_model_id if run else None,
    )

    source_client = FGAClient(
        api_url=config.api_url,
        store_id=pin.store_id,
        model_id=pin.model_id,
        timeout=config.timeout,
    )
    dashboard_repository = SqlDashboardMigrationRepository()
    sources = (
        KnowledgePermissionMigrationSource(SqlKnowledgeMigrationRepository()),
        ChannelPermissionMigrationSource(SqlChannelMigrationRepository()),
        ApplicationPermissionMigrationSource(SqlApplicationMigrationRepository()),
        ToolPermissionMigrationSource(SqlToolMigrationRepository()),
        DashboardPermissionMigrationSource(dashboard_repository),
    )
    source_provider = LiveMigrationSourceProvider(
        source_client=source_client,
        actual_store_id=pin.store_id,
        source_model_id=pin.model_id,
        sources=sources,
        dashboard_repository=dashboard_repository,
        identity_state_source=LegacyIdentityPermissionMigrationSource(),
    )
    target_writer = SqlOpenFGAMigrationTargetWriter(source_client=source_client)
    coordinator = F048MigrationCoordinator(
        source_provider=source_provider,
        run_store=run_store,
        model_publisher=OpenFGAMigrationModelPublisher(
            source_client=source_client,
            environment=_environment_name(live_settings.environment),
            predecessor_model_id=pin.model_id,
        ),
        target_writer=target_writer,
    )
    verifier = F048MigrationVerifier(
        run_store=run_store,
        evidence_provider=LiveMigrationEvidenceProvider(
            source_client=source_client,
            target_writer=target_writer,
        ),
    )
    return F048MigrationRuntime(
        coordinator=coordinator,
        verifier=verifier,
        source_client=source_client,
        target_writer=target_writer,
    )
