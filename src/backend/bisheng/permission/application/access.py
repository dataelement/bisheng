"""Process-local access to the initialized F048 runtime."""

from __future__ import annotations

from bisheng.permission.application.resource_authorization import (
    ResourceAuthorizationRegistry,
)
from bisheng.permission.application.runtime import F048PermissionRuntime

_runtime: F048PermissionRuntime | None = None
_resource_adapters: dict[str, object] = {}
_resource_registry: ResourceAuthorizationRegistry | None = None


def configure_f048_runtime(
    runtime: F048PermissionRuntime,
    *,
    resource_adapters: dict[str, object] | None = None,
    resource_registry: ResourceAuthorizationRegistry | None = None,
) -> None:
    global _runtime, _resource_adapters, _resource_registry
    _runtime = runtime
    _resource_adapters = dict(resource_adapters or {})
    _resource_registry = resource_registry


def get_f048_runtime() -> F048PermissionRuntime:
    if _runtime is None:
        raise RuntimeError("F048 permission runtime is not configured")
    return _runtime


def has_f048_runtime() -> bool:
    """Return whether this process has completed F048 runtime initialization."""

    return _runtime is not None


def get_f048_resource_adapter(resource_type: str):
    adapter = _resource_adapters.get(resource_type)
    if adapter is None:
        raise RuntimeError(f"F048 resource adapter is not configured: {resource_type}")
    return adapter


def get_f048_resource_registry() -> ResourceAuthorizationRegistry:
    if _resource_registry is None:
        raise RuntimeError("F048 resource registry is not configured")
    return _resource_registry


def clear_f048_runtime() -> None:
    global _runtime, _resource_adapters, _resource_registry
    _runtime = None
    _resource_adapters = {}
    _resource_registry = None
