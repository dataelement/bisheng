"""Permission-owned, read-only effects for explicit F118 maintenance."""

from contextlib import asynccontextmanager

from bisheng.permission.domain.services.maintenance_guard import maintenance_guard as maintenance_guard
from bisheng.permission.domain.services.projection_effects import finalization_effect as finalization_effect
from bisheng.permission.domain.services.projection_effects import terminal_graph_effect as terminal_graph_effect
from bisheng.permission.domain.services.projection_plan import build_projection_operation as build_projection_operation
from bisheng.permission.domain.services.projection_plan import (
    projection_request_checksum as projection_request_checksum,
)
from bisheng.permission.domain.services.projection_service import restore_projection_plan as restore_projection_plan
from bisheng.permission.domain.services.resource_lifecycle_policy import build_create_plan as build_create_plan
from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan as build_delete_plan


@asynccontextmanager
async def open_history_runtime(settings, *, pin, sessions, apply, store=None, sharing_reader_factory=None):
    from types import SimpleNamespace

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.core.openfga.client import FGAClient
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from bisheng.permission.application.control_state import SqlPermissionControlState
    from bisheng.permission.application.runtime import F048PermissionRuntime
    from bisheng.permission.application.sql_runtime import build_sql_projection_runtime
    from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
        PermissionMigrationSnapshotRepository,
    )
    from bisheng.permission.domain.services.projection_service import ProjectionService

    conf = settings.openfga
    if not conf.enabled or conf.force_write_model or conf.dual_model_mode or conf.legacy_model_id:
        raise KnowledgeOperationPlanConflictError(reason="history_prepare_read_pinned_fga_configuration_required")
    actual = await discover_openfga_runtime(
        conf,
        expected_model=None,
        allow_bootstrap=False,
        required_store_id=pin["store_id"],
        required_model_id=pin["model_id"],
    )
    if actual.model_checksum != pin["model_checksum"]:
        raise KnowledgeOperationPlanConflictError(reason="history_prepare_physical_pin_changed")
    client = FGAClient(api_url=conf.api_url, store_id=pin["store_id"], model_id=pin["model_id"], timeout=conf.timeout)
    try:
        native = None
        if apply:

            class MaintenanceState(SqlPermissionControlState):
                async def current_catalog(self):
                    with tenant_execution_scope(1):
                        async with sessions() as session, session.begin():
                            repo = PermissionMigrationSnapshotRepository()
                            environment = await repo.adiscover_environment(session)
                            catalog = await repo.aload_catalog_baseline(session, environment=environment)
                    current = {
                        "release_id": catalog.release.id,
                        "checksum": catalog.release.checksum,
                        "store_id": catalog.authorization.store_id,
                        "model_id": catalog.authorization.model_id,
                        "model_checksum": catalog.authorization.model_checksum,
                    }
                    if current != pin:
                        raise KnowledgeOperationPlanConflictError(reason="history_prepare_catalog_pin_changed")
                    return SimpleNamespace(**current)

            components = await build_sql_projection_runtime(client, session_factory=sessions)
            native = F048PermissionRuntime(
                client=client,
                state=MaintenanceState(session_factory=sessions),
                marker=components.marker,
                decision=None,
                projection=ProjectionService(
                    **{
                        name: getattr(components, name)
                        for name in ("repository", "marker", "scope_guard", "fga", "finalizer")
                    }
                ),
                sources=None,
                owner=None,
                grants=None,
                modes=None,
                explain=None,
            )
        yield SimpleNamespace(
            sessions=sessions,
            store=store,
            history_client=client,
            client=client,
            history_runtime=native,
            sharing_reader_factory=sharing_reader_factory,
        )
    finally:
        await client.close()


async def discover_migration_environment(session, environment=None):
    from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
        PermissionMigrationSnapshotRepository,
    )

    return await PermissionMigrationSnapshotRepository().adiscover_environment(session, environment=environment)
