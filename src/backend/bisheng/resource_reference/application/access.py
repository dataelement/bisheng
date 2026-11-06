"""Explicit process-local composition; never install a permissive fallback."""

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime

_runtime: ReferenceBindingRuntime | None = None


def configure_reference_binding_runtime(runtime: ReferenceBindingRuntime | None) -> None:
    global _runtime
    if runtime is not None and not isinstance(runtime, ReferenceBindingRuntime):
        raise TypeError("a fully assembled reference runtime is required")
    _runtime = runtime


def get_reference_binding_runtime_sync() -> ReferenceBindingRuntime:
    if _runtime is None:
        raise ReferenceCoverageNotReadyError(reason="reference_runtime_unconfigured")
    return _runtime


async def get_reference_binding_runtime() -> ReferenceBindingRuntime:
    return get_reference_binding_runtime_sync()
