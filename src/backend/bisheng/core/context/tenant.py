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

**v2.5.1 F012 extensions**:
  - ``visible_tenant_ids``: frozenset of tenant ids the current request can
    SEE via IN-list filter (consumed by F013 tenant_filter event listener).
    For Root users: ``{1}``; for Child users: ``{leaf_id, 1}``; for global
    super admins without admin-scope: ``None`` (no filter).
  - ``strict_tenant_filter()``: opt-in CM that forces strict ``tenant_id =
    current_tenant_id`` filtering instead of IN-list — used by F016 quota
    counting and F012 owned-resource counting where IN-list over-counts.
  - ``_admin_scope_tenant_id``: F019 global-super "management view" override;
    ``get_current_tenant_id()`` returns this when set, taking priority over
    ``current_tenant_id``. Always ``None`` for non-super users.
  - ``_is_management_api``: F019 flag indicating the current request is
    hitting a whitelisted management API — read by the tenant_filter event
    to decide whether to honour the admin scope override.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import FrozenSet, Optional

DEFAULT_TENANT_ID: int = 1

# ---------------------------------------------------------------------------
# v2.5.0 baseline (signatures preserved — do not change).
# ---------------------------------------------------------------------------

current_tenant_id: ContextVar[Optional[int]] = ContextVar(
    'current_tenant_id', default=None,
)

_bypass_tenant_filter: ContextVar[bool] = ContextVar(
    '_bypass_tenant_filter', default=False,
)

# ---------------------------------------------------------------------------
# v2.5.1 F012 extensions.
# ---------------------------------------------------------------------------

visible_tenant_ids: ContextVar[Optional[FrozenSet[int]]] = ContextVar(
    'visible_tenant_ids', default=None,
)

_strict_tenant_filter: ContextVar[bool] = ContextVar(
    '_strict_tenant_filter', default=False,
)

_admin_scope_tenant_id: ContextVar[Optional[int]] = ContextVar(
    '_admin_scope_tenant_id', default=None,
)

_is_management_api: ContextVar[bool] = ContextVar(
    '_is_management_api', default=False,
)


# ---------------------------------------------------------------------------
# Public helpers — current_tenant_id (v2.5.0 signature preserved).
# ---------------------------------------------------------------------------

def get_current_tenant_id() -> Optional[int]:
    """Return the current tenant ID, honouring the F019 admin-scope override.

    **v2.5.1 priority** (v2.5.0 callers see no behavioural change until
    F019 actually starts setting ``_admin_scope_tenant_id``):

    1. If ``_admin_scope_tenant_id`` is not None — return it (F019 super
       admin has switched management view).
    2. Otherwise — return ``current_tenant_id.get()`` (JWT leaf tenant).
    """
    scope = _admin_scope_tenant_id.get()
    if scope is not None:
        return scope
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


# ---------------------------------------------------------------------------
# v2.5.1 F012 helpers — visible_tenant_ids / strict / admin-scope.
# ---------------------------------------------------------------------------

def get_visible_tenant_ids() -> Optional[FrozenSet[int]]:
    """Return the IN-list of tenant ids the current request can see.

    ``None`` means "no IN-list filter injected" — used for global super
    admins without an active admin-scope. The F013 event listener reads
    this and either injects ``WHERE tenant_id IN (...)`` or skips filtering
    entirely. A non-None empty frozenset is not currently used; the empty
    case is equivalent to ``{current_tenant_id}`` in practice.
    """
    return visible_tenant_ids.get()


def set_visible_tenant_ids(ids: Optional[FrozenSet[int]]):
    """Set the visible tenant ids frozenset. Returns a reset token."""
    return visible_tenant_ids.set(ids)


@contextmanager
def strict_tenant_filter():
    """Force strict ``tenant_id = current_tenant_id`` filtering.

    Used when IN-list over-counts (e.g. F016 quota, F012 owned-resource
    counting in sync_user): under IN-list, Root's own resources count
    against Child users too, which inflates the count.
    """
    token = _strict_tenant_filter.set(True)
    try:
        yield
    finally:
        _strict_tenant_filter.reset(token)


def is_strict_tenant_filter() -> bool:
    """Return True when the current context demands strict equality."""
    return _strict_tenant_filter.get()


def get_admin_scope_tenant_id() -> Optional[int]:
    """Return the F019 admin-scope override, or None if unset."""
    return _admin_scope_tenant_id.get()


def set_admin_scope_tenant_id(tenant_id: Optional[int]):
    """Set the F019 admin-scope override. Returns a reset token."""
    return _admin_scope_tenant_id.set(tenant_id)


def get_is_management_api() -> bool:
    """Return True when the current request is a whitelisted management API."""
    return _is_management_api.get()


def set_is_management_api(value: bool):
    """Set the management-api flag. Returns a reset token."""
    return _is_management_api.set(value)
