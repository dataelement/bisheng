"""Celery signals for tenant context propagation.

- ``before_task_publish``: Injects current tenant_id into task headers.
- ``task_prerun``: Restores tenant_id ContextVar from task headers on worker side.
- ``task_postrun``: Resets tenant_id ContextVar to avoid thread-pool leakage.

This module is imported by ``worker/main.py`` to trigger signal registration.
"""

from celery.signals import before_task_publish, task_prerun, task_postrun
from loguru import logger

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)


@before_task_publish.connect
def inject_tenant_header(headers=None, **kwargs):
    """Write current tenant_id into Celery task headers before publishing."""
    tid = get_current_tenant_id()
    if tid is not None and headers is not None:
        headers['tenant_id'] = tid


@task_prerun.connect
def restore_tenant_context(sender=None, **kwargs):
    """Restore tenant_id ContextVar from task headers on worker side."""
    request = sender.request
    tenant_id = (getattr(request, 'headers', None) or {}).get('tenant_id')
    if tenant_id is not None:
        set_current_tenant_id(int(tenant_id))
    else:
        set_current_tenant_id(DEFAULT_TENANT_ID)


@task_postrun.connect
def reset_tenant_context(sender=None, **kwargs):
    """Reset tenant_id ContextVar after task execution.

    Prevents tenant context from leaking when Celery reuses threads.
    """
    current_tenant_id.set(None)
