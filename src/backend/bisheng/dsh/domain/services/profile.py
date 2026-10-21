"""Tenant scope for local DSH management and usage repositories."""

from contextlib import contextmanager

from bisheng.core.context import tenant as context


@contextmanager
def profile_scope(tenant_id: int):
    tokens = [
        context.set_current_tenant_id(tenant_id),
        context.set_admin_scope_tenant_id(None),
        context.set_visible_tenant_ids(frozenset({tenant_id})),
        context._bypass_tenant_filter.set(False),
    ]
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)
