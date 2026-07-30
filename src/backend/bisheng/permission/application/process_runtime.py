"""Process lifecycle helpers for the single F048 permission runtime."""

from __future__ import annotations

import asyncio
from typing import Protocol

from loguru import logger

from bisheng.core.openfga.client import FGAClient
from bisheng.permission.application.access import configure_f048_runtime
from bisheng.permission.application.runtime import (
    F048PermissionRuntime,
    F048RuntimeComponents,
    build_f048_permission_runtime,
)
from bisheng.permission.application.sql_runtime import (
    ExternalProjectionScopePort,
)

DEFAULT_F048_HEARTBEAT_INTERVAL_SECONDS = 15


class F048ProcessManagerPort(Protocol):
    async def bind_catalog_runtime(
        self,
        resolver,
    ) -> None: ...

    async def heartbeat(self) -> bool: ...

    def readiness(self) -> dict: ...


async def initialize_f048_background_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> F048RuntimeComponents:
    """Compose the business-independent runtime for a background process."""

    components = await build_f048_permission_runtime(
        client,
        external_scopes=external_scopes,
    )
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
