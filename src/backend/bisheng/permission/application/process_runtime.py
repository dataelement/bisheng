"""Process lifecycle helpers for the single F048 permission runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger

from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    PermissionPublishNotReadyError,
)
from bisheng.core.context import FunctionContextManager
from bisheng.core.context.manager import app_context
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.application.runtime import (
    F048PermissionRuntime,
    F048RuntimeComponents,
    build_f048_permission_runtime,
)
from bisheng.permission.application.sql_runtime import (
    ExternalProjectionScopePort,
)

DEFAULT_F048_HEARTBEAT_INTERVAL_SECONDS = 15
F048_PERMISSION_RUNTIME_CONTEXT = "permission_runtime"


class F048ProcessManagerPort(Protocol):
    async def bind_catalog_runtime(
        self,
        resolver,
    ) -> None: ...

    async def heartbeat(self) -> bool: ...

    async def mark_migration_required(self, *, reason: str = ...) -> None: ...

    def readiness(self) -> dict: ...


RuntimeInitializer = Callable[[FGAClient], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ProcessPermissionRuntime:
    runtime: Any
    heartbeat_task: asyncio.Task


def _components(runtime: Any) -> F048RuntimeComponents:
    components = getattr(runtime, "components", runtime)
    if not isinstance(components, F048RuntimeComponents):
        raise TypeError("Permission runtime initializer returned an invalid composition")
    return components


def register_f048_permission_runtime_context(
    initializer: RuntimeInitializer,
) -> None:
    """Register the process permission composition without initializing it."""

    from bisheng.common.permission_identity import configure_tenant_admin_checker
    from bisheng.permission.application.relation_api import is_tenant_admin

    configure_tenant_admin_checker(is_tenant_admin)

    try:
        app_context.get_context(F048_PERMISSION_RUNTIME_CONTEXT)
        return
    except KeyError:
        pass

    async def initialize() -> ProcessPermissionRuntime:
        manager = app_context.get_context("openfga")
        client = await manager.async_get_instance()
        readiness = manager.readiness()
        if readiness.get("migration_required"):
            # Report what actually latched the gate. A fenced Catalog left by a
            # crashed publish reported "migration is required" here, which sent
            # the operator looking for a migration that was never pending.
            raise PermissionPublishNotReadyError(
                msg=str(readiness.get("error") or "Permission data migration is required")
            )
        # Fresh install has no legacy data and never runs the forward-only data
        # migration, so nothing else would create the initial CURRENT Catalog.
        # Seed it here (idempotent no-op once present). Reaching this point means
        # migration is not required, so this only ever fires on a brand-new
        # deployment; an upgrade raised above until the operator migrates.
        from bisheng.common.services.config_service import settings
        from bisheng.permission.application.catalog_bootstrap import (
            seed_initial_permission_catalog,
        )

        seeded_fresh_catalog = await seed_initial_permission_catalog(
            client,
            store_id=str(readiness.get("store_id") or ""),
            model_id=str(readiness.get("model_id") or ""),
            model_checksum=str(readiness.get("model_checksum") or ""),
            environment=settings.environment,
        )
        try:
            runtime = await initializer(client)
        except (
            AuthorizationModelMismatchError,
            PermissionPublishNotReadyError,
        ) as exc:
            await manager.mark_migration_required(reason=str(exc) or "permission_data_migration_required")
            raise
        if seeded_fresh_catalog:
            await _components(runtime).marker.wait_until_ready(
                timeout_seconds=float(settings.openfga.recent_consistency_window_seconds) + 5.0,
            )
        await bind_f048_process_runtime(
            manager,
            _components(runtime).facade,
        )
        heartbeat_task = asyncio.create_task(
            run_f048_process_heartbeat(manager),
            name="permission-runtime-heartbeat",
        )
        return ProcessPermissionRuntime(
            runtime=runtime,
            heartbeat_task=heartbeat_task,
        )

    async def cleanup(context: ProcessPermissionRuntime) -> None:
        if context.heartbeat_task is not None:
            context.heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await context.heartbeat_task
        from bisheng.permission.application.access import clear_f048_runtime

        clear_f048_runtime()

    app_context.register_context(
        FunctionContextManager(
            name=F048_PERMISSION_RUNTIME_CONTEXT,
            init_func=initialize,
            cleanup_func=cleanup,
        ),
        dependencies=["openfga"],
        lazy=True,
    )


async def get_f048_process_runtime() -> Any:
    context: ProcessPermissionRuntime = await app_context.async_get_instance(F048_PERMISSION_RUNTIME_CONTEXT)
    return context.runtime


async def ensure_f048_process_runtime_ready(*, expected_role: str) -> dict:
    """Return complete process readiness after forcing lazy initialization."""

    await get_f048_process_runtime()
    manager = app_context.get_context("openfga")
    readiness = manager.readiness()
    required = (
        "store_id",
        "model_id",
        "model_checksum",
        "catalog_release_id",
        "catalog_checksum",
    )
    if (
        not readiness.get("ready")
        or readiness.get("instance_role") != expected_role
        or any(readiness.get(field) in (None, "") for field in required)
    ):
        raise RuntimeError(f"{expected_role} permission runtime is not ready or has incomplete pins")
    return readiness


async def initialize_f048_background_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> F048RuntimeComponents:
    """Compose the business-independent runtime for a background process.

    This layer cannot know the business resource adapters, so it leaves the
    resource registry UNSET. A process that only needs the permission runtime may
    stop here; a process that runs business code (tool init, resource checks) must
    NOT — ``check_business_action`` would raise "F048 resource registry is not
    configured". Those processes call
    ``bisheng.api.services.f048_permission_runtime.initialize_f048_worker_runtime``,
    which wraps this and attaches the same resource composition the API installs.
    """

    components = await build_f048_permission_runtime(
        client,
        external_scopes=external_scopes,
    )
    from bisheng.permission.application.access import configure_f048_runtime

    configure_f048_runtime(components.facade)
    return components


async def bind_f048_process_runtime(
    manager: F048ProcessManagerPort,
    runtime: F048PermissionRuntime,
) -> dict:
    """Bind SQL CURRENT Catalog evidence before publishing process readiness."""

    await manager.bind_catalog_runtime(runtime.current_catalog)
    if not await manager.heartbeat():
        raise RuntimeError("F048 process runtime initial heartbeat failed")
    readiness = manager.readiness()
    if not readiness.get("ready"):
        raise RuntimeError("F048 process runtime is not ready")
    return readiness


async def run_f048_process_heartbeat(
    manager: F048ProcessManagerPort,
    *,
    interval_seconds: float = DEFAULT_F048_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Refresh the dynamic Catalog pin and process heartbeat until cancelled."""

    if interval_seconds <= 0:
        raise ValueError("F048 heartbeat interval must be positive")
    while True:
        try:
            if not await manager.heartbeat():
                logger.error(
                    "F048 process heartbeat is not ready: {}",
                    manager.readiness().get("error"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("F048 process heartbeat failed")
        await asyncio.sleep(interval_seconds)
