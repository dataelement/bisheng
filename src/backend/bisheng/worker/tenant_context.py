"""Celery signals for tenant context propagation.

- ``before_task_publish``: Injects current tenant_id into task headers.
- ``task_prerun``: Restores tenant_id ContextVar from task headers on worker side.
- ``task_postrun``: Resets tenant_id ContextVar to avoid thread-pool leakage.

This module is imported by ``worker/main.py`` to trigger signal registration.
"""

from celery.signals import before_task_publish, task_postrun, task_prerun

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)

F048_PERMISSION_TASK_PREFIX = "bisheng.worker.permission."
# The legacy failed_tuple compensation queue is processed Store-wide.
TENANT_AGNOSTIC_LEGACY_PERMISSION_TASKS = frozenset(
    {
        "bisheng.worker.permission.retry_failed_tuples.cleanup_succeeded_failed_tuples",
        "bisheng.worker.permission.retry_failed_tuples.retry_failed_tuples",
    }
)


class PermissionTaskTenantContextError(RuntimeError):
    """A permission task cannot run without an explicit valid tenant."""


def _task_name(sender) -> str:
    if isinstance(sender, str):
        return sender
    name = getattr(sender, "name", "")
    return name if isinstance(name, str) else ""


def _is_permission_task(sender, headers: dict | None) -> bool:
    task_name = _task_name(sender)
    return bool(
        (headers or {}).get("f048_permission_task")
        or (
            task_name.startswith(F048_PERMISSION_TASK_PREFIX)
            and task_name not in TENANT_AGNOSTIC_LEGACY_PERMISSION_TASKS
        )
    )


def _parse_tenant_id(value) -> int:
    if isinstance(value, bool):
        raise PermissionTaskTenantContextError("permission task tenant_id must be a positive integer")
    try:
        tenant_id = int(value)
    except (TypeError, ValueError) as exc:
        raise PermissionTaskTenantContextError("permission task tenant_id must be a positive integer") from exc
    if tenant_id <= 0:
        raise PermissionTaskTenantContextError("permission task tenant_id must be a positive integer")
    return tenant_id


def inject_tenant_header(sender=None, headers=None, **kwargs):
    """Write current tenant_id into Celery task headers before publishing."""
    tid = get_current_tenant_id()
    permission_task = _is_permission_task(sender, headers)
    if permission_task and (tid is None or headers is None):
        raise PermissionTaskTenantContextError("permission task publish requires an explicit tenant context")
    if tid is not None and headers is not None:
        headers["tenant_id"] = _parse_tenant_id(tid)
        if permission_task:
            headers["f048_permission_task"] = True


def restore_tenant_context(sender=None, **kwargs):
    """Restore tenant_id ContextVar from task headers on worker side."""
    request = sender.request
    headers = getattr(request, "headers", None) or {}
    tenant_id = headers.get("tenant_id")
    permission_task = _is_permission_task(sender, headers)
    if permission_task:
        current_tenant_id.set(None)
        if tenant_id is None:
            raise PermissionTaskTenantContextError("permission task execution requires tenant_id header")
        token = set_current_tenant_id(_parse_tenant_id(tenant_id))
    elif tenant_id is not None:
        token = set_current_tenant_id(_parse_tenant_id(tenant_id))
    else:
        token = set_current_tenant_id(DEFAULT_TENANT_ID)
    request._bisheng_tenant_context_token = token


def reset_tenant_context(sender=None, **kwargs):
    """Reset tenant_id ContextVar after task execution.

    Prevents tenant context from leaking when Celery reuses threads.
    """
    request = getattr(sender, "request", None)
    token = getattr(request, "_bisheng_tenant_context_token", None)
    if token is not None:
        try:
            current_tenant_id.reset(token)
        except (LookupError, RuntimeError, TypeError, ValueError):
            current_tenant_id.set(None)
        finally:
            request._bisheng_tenant_context_token = None
    else:
        current_tenant_id.set(None)


# Register after defining the handlers so direct unit tests still exercise the
# real functions when Celery signals are replaced with import-time test stubs.
before_task_publish.connect(inject_tenant_header)
task_prerun.connect(restore_tenant_context)
task_postrun.connect(reset_tenant_context)
