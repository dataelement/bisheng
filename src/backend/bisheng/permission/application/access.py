"""Process-local access to the initialized F048 runtime."""

from __future__ import annotations

from bisheng.permission.application.resource_authorization import (
    ResourceAuthorizationRegistry,
)
from bisheng.permission.application.runtime import F048PermissionRuntime

_runtime: F048PermissionRuntime | None = None
_resource_adapters: dict[str, object] = {}
_resource_registry: ResourceAuthorizationRegistry | None = None
_subject_directory: object | None = None


def configure_f048_runtime(
    runtime: F048PermissionRuntime,
    *,
    resource_adapters: dict[str, object] | None = None,
    resource_registry: ResourceAuthorizationRegistry | None = None,
    subject_directory: object | None = None,
) -> None:
    global _runtime, _resource_adapters, _resource_registry, _subject_directory
    _runtime = runtime
    _resource_adapters = dict(resource_adapters or {})
    _resource_registry = resource_registry
    _subject_directory = subject_directory


async def _ensure_f048_runtime() -> None:
    from bisheng.permission.application.process_runtime import get_f048_process_runtime

    # The initializer publishes process-local adapters while composing the
    # runtime. Always wait for the Context to reach READY so a concurrent call
    # cannot observe those adapters before Catalog binding and heartbeat pass.
    await get_f048_process_runtime()


async def get_f048_runtime() -> F048PermissionRuntime:
    await _ensure_f048_runtime()
    if _runtime is None:
        raise RuntimeError("F048 permission runtime is not configured")
    return _runtime


async def get_f048_resource_adapter(resource_type: str):
    await _ensure_f048_runtime()
    adapter = _resource_adapters.get(resource_type)
    if adapter is None:
        raise RuntimeError(f"F048 resource adapter is not configured: {resource_type}")
    return adapter


async def get_f048_resource_registry() -> ResourceAuthorizationRegistry:
    await _ensure_f048_runtime()
    if _resource_registry is None:
        raise RuntimeError("F048 resource registry is not configured")
    return _resource_registry


def clear_f048_runtime() -> None:
    global _runtime, _resource_adapters, _resource_registry, _subject_directory
    _runtime = None
    _resource_adapters = {}
    _resource_registry = None
    _subject_directory = None


def get_grant_subject_directory():
    """Return the business-owned directory installed by the composition root."""
    if _subject_directory is None:
        raise RuntimeError("Grant subject directory is not configured")
    return _subject_directory
