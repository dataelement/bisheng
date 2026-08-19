from __future__ import annotations

from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantExecutor,
    ResourceGrantExecutorNotFoundError,
    ResourceGrantVerificationResult,
)


class ResourceGrantExecutorRegistry:
    """Frozen resource-type router populated only by the composition root."""

    def __init__(self) -> None:
        self._executors: dict[str, ResourceGrantExecutor] = {}
        self._frozen = False

    def register(
        self,
        resource_type: str,
        executor: ResourceGrantExecutor,
    ) -> None:
        if self._frozen:
            raise RuntimeError("resource grant executor registry is frozen")
        normalized_type = self._normalize_resource_type(resource_type)
        if normalized_type in self._executors:
            raise ValueError(f"resource grant executor already registered: {normalized_type}")
        if getattr(executor, "resource_type", None) != normalized_type:
            raise ValueError(f"resource grant executor type mismatch: {normalized_type}")
        if not callable(getattr(executor, "execute", None)) or not callable(getattr(executor, "verify", None)):
            raise ValueError(f"resource grant executor protocol mismatch: {normalized_type}")
        self._executors[normalized_type] = executor

    def freeze(self, *, required_resource_types: set[str]) -> None:
        normalized_required = {
            self._normalize_resource_type(resource_type) for resource_type in required_resource_types
        }
        missing = sorted(normalized_required - self._executors.keys())
        if missing:
            raise ValueError(f"resource grant executor missing: {', '.join(missing)}")
        self._frozen = True

    async def execute(self, command: ResourceGrantCommand) -> None:
        executor = self._get_executor(command.resource_type)
        await executor.execute(command)

    async def verify(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult:
        executor = self._get_executor(command.resource_type)
        return await executor.verify(command)

    def _get_executor(self, resource_type: str) -> ResourceGrantExecutor:
        if not self._frozen:
            raise RuntimeError("resource grant executor registry is not frozen")
        normalized_type = self._normalize_resource_type(resource_type)
        executor = self._executors.get(normalized_type)
        if executor is None:
            raise ResourceGrantExecutorNotFoundError(f"resource grant executor not registered: {normalized_type}")
        return executor

    @staticmethod
    def _normalize_resource_type(resource_type: str) -> str:
        if not isinstance(resource_type, str) or not resource_type.strip():
            raise ValueError("resource_type must be a non-empty string")
        return resource_type.strip()


__all__ = ["ResourceGrantExecutorRegistry"]
