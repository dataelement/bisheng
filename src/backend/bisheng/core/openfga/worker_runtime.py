"""OpenFGA runtime validation shared by background workers."""

from __future__ import annotations

from typing import Protocol


class WorkerFGARuntimeManager(Protocol):
    """Minimal manager contract required by worker startup."""

    async def async_get_instance(self): ...

    async def heartbeat(self) -> bool: ...

    def readiness(self) -> dict: ...


async def ensure_background_fga_runtime(
    manager: WorkerFGARuntimeManager,
    *,
    expected_role: str,
) -> dict:
    """Initialize and verify one background process's complete F048 pin."""

    instance = await manager.async_get_instance()
    healthy = bool(instance) and await manager.heartbeat()
    readiness = manager.readiness()
    required = (
        "store_id",
        "model_id",
        "model_checksum",
        "catalog_release_id",
        "catalog_checksum",
    )
    if (
        not healthy
        or not readiness.get("ready")
        or readiness.get("instance_role") != expected_role
        or any(readiness.get(field) in (None, "") for field in required)
    ):
        raise RuntimeError(f"{expected_role} F048 OpenFGA runtime is not ready or has incomplete pins")
    return readiness


async def ensure_worker_fga_runtime(manager: WorkerFGARuntimeManager) -> dict:
    """Verify the Celery worker's complete single-model runtime pin."""

    return await ensure_background_fga_runtime(
        manager,
        expected_role="celery",
    )


async def ensure_linsight_fga_runtime(
    manager: WorkerFGARuntimeManager,
) -> dict:
    """Verify the Linsight worker's complete single-model runtime pin."""

    return await ensure_background_fga_runtime(
        manager,
        expected_role="linsight",
    )
