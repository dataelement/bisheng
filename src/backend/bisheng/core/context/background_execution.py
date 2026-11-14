"""Process-local provenance from the actual background executor lifecycle.

A tenant value alone is not background execution. The executor owns issuance
and supplies a pure live-context check; HTTP schemas never carry this object.
"""

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed


@dataclass(frozen=True, slots=True, eq=False)
class BackgroundTaskContext:
    tenant_id: int
    task_id: str
    task_name: str


_binding: ContextVar[tuple[BackgroundTaskContext, Callable[[], bool]] | None] = ContextVar(
    "trusted_background_task", default=None
)


def bind_background_task(tenant_id: int, task_id: str, task_name: str, *, is_current: Callable[[], bool]) -> Token:
    if (
        type(tenant_id) is not int
        or tenant_id <= 0
        or tenant_id != get_current_tenant_id()
        or is_tenant_filter_bypassed()
        or not isinstance(task_id, str)
        or not task_id
        or not isinstance(task_name, str)
        or not task_name
        or not callable(is_current)
        or not is_current()
    ):
        return _binding.set(None)
    return _binding.set((BackgroundTaskContext(tenant_id, task_id, task_name), is_current))


def clear_background_task() -> Token:
    return _binding.set(None)


def reset_background_task(token: Token) -> None:
    try:
        _binding.reset(token)
    except (LookupError, RuntimeError, TypeError, ValueError):
        _binding.set(None)


def get_current_background_task() -> BackgroundTaskContext | None:
    binding = _binding.get()
    if binding is None:
        return None
    context, is_current = binding
    if context.tenant_id != get_current_tenant_id() or is_tenant_filter_bypassed() or not is_current():
        return None
    return context
