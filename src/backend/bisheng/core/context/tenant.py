"""Tenant context management using Python ContextVar.

Provides request-scoped tenant isolation. The ContextVar is set by:
- HTTP middleware (CustomMiddleware) — from JWT cookie
- WebSocket middleware — from WS cookie
- Celery signal (task_prerun) — from task headers

The SQLAlchemy event hooks in tenant_filter.py read this ContextVar to
automatically inject WHERE tenant_id=X on queries and fill tenant_id on inserts.

Usage:
    set_current_tenant_id(2)
    assert get_current_tenant_id() == 2

    with bypass_tenant_filter():
        # Queries here skip tenant_id filtering (e.g. system admin cross-tenant)
        ...
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

DEFAULT_TENANT_ID: int = 1

current_tenant_id: ContextVar[Optional[int]] = ContextVar(
    'current_tenant_id', default=None,
)

_bypass_tenant_filter: ContextVar[bool] = ContextVar(
    '_bypass_tenant_filter', default=False,
)


def get_current_tenant_id() -> Optional[int]:
    """Return the current tenant ID, or None if not set."""
    return current_tenant_id.get()


def set_current_tenant_id(tenant_id: int):
    """Set the current tenant ID in the context. Returns a reset token."""
    return current_tenant_id.set(tenant_id)


@contextmanager
def bypass_tenant_filter():
    """Context manager to temporarily disable tenant filtering.

    Used for system admin cross-tenant queries and initialization code.
    """
    token = _bypass_tenant_filter.set(True)
    try:
        yield
    finally:
        _bypass_tenant_filter.reset(token)


def is_tenant_filter_bypassed() -> bool:
    """Return True if tenant filtering is currently bypassed."""
    return _bypass_tenant_filter.get()
