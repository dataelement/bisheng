"""Explicit process-local source read wiring, never a permission fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError

if TYPE_CHECKING:
    from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime

_runtime: ReferenceSourceReadRuntime | None = None


def configure_reference_read_runtime(runtime: ReferenceSourceReadRuntime | None) -> None:
    global _runtime
    if runtime is not None:
        if not all(
            callable(getattr(runtime, name, None))
            for name in ("ainspect_source", "arequire_source_valid", "arequire_transient_valid")
        ):
            raise TypeError("a fully assembled source read runtime is required")
        from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime

        if not isinstance(runtime, ReferenceSourceReadRuntime):
            raise TypeError("a fully assembled source read runtime is required")
    _runtime = runtime


async def get_reference_read_runtime() -> ReferenceSourceReadRuntime:
    if _runtime is None:
        raise ReferenceCoverageNotReadyError(reason="reference_read_runtime_unconfigured")
    return _runtime
