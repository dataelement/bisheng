"""Celery signals for tenant context propagation.

- ``before_task_publish``: Injects current tenant_id into task headers.
- ``task_prerun``: Restores tenant_id ContextVar from task headers on worker side.
- ``task_postrun``: Resets tenant_id ContextVar to avoid thread-pool leakage.

This module is imported by ``worker/main.py`` to trigger signal registration.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from celery import current_task
from celery.signals import before_task_publish, task_postrun, task_prerun

from bisheng.core.context.background_execution import (
    bind_background_task,
    clear_background_task,
    reset_background_task,
)
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
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int:
        raise PermissionTaskTenantContextError("permission task tenant_id must be a positive integer")
    tenant_id = value
    if tenant_id <= 0:
        raise PermissionTaskTenantContextError("permission task tenant_id must be a positive integer")
    return tenant_id


trusted_copy_tenant = ContextVar("trusted_copy_tenant", default=None)
_COPY_TASKS = frozenset(
    {"bisheng.worker.knowledge.file_worker.file_copy_celery", "bisheng.worker.knowledge.qa.copy_qa_knowledge_celery"}
)


def _is_copy_task(sender):
    return (sender if isinstance(sender, str) else getattr(sender, "name", "")) in _COPY_TASKS


_WORKFLOW_TASKS = frozenset(
    {
        "bisheng.worker.workflow.tasks.execute_workflow",
        "bisheng.worker.workflow.tasks.continue_workflow",
        "bisheng.worker.workflow.tasks.stop_workflow",
    }
)
_EXPORT_TASK = "runtime_audit_export"


def _durable_task_tenant(sender, header):
    name = _task_name(sender)
    if name not in _WORKFLOW_TASKS and name != _EXPORT_TASK:
        return header
    request = sender.request
    args = getattr(request, "args", ()) or ()
    kwargs = getattr(request, "kwargs", {}) or {}
    if name in _WORKFLOW_TASKS:
        from bisheng.workflow.domain.repositories.creation_repository import CreationRepository

        resource_id = kwargs.get("workflow_id") or (args[1] if len(args) > 1 else None)
        actual = CreationRepository.tenant_for_message(resource_id) if resource_id else None
    else:
        from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import (
            RuntimeAuditExportRepository,
        )

        job_id = kwargs.get("job_id") or (args[0] if args else None)
        supplied = kwargs.get("tenant_id", args[1] if len(args) > 1 else None)
        actual = RuntimeAuditExportRepository.tenant_for_message(job_id) if job_id else None
        if actual is not None and _parse_tenant_id(supplied) != actual:
            raise PermissionTaskTenantContextError("export payload disagrees with persistent target")
    if actual is None or (header is not None and _parse_tenant_id(header) != actual):
        raise PermissionTaskTenantContextError("workload tenant proof missing or conflicting")
    return _parse_tenant_id(actual)


@contextmanager
def durable_workload_scope(kind, resource_id, payload_tenant=None):
    # Celery signal receivers can log an exception without aborting execution.
    # Enforce the same proof inside the task body, before restoring snapshots.
    from bisheng.core.context.tenant import tenant_execution_scope

    task = current_task._get_current_object()
    header = (
        (getattr(getattr(task, "request", None), "headers", None) or {}).get("tenant_id")
        if task
        else get_current_tenant_id()
    )
    if kind == "workflow":
        from bisheng.workflow.domain.repositories.creation_repository import CreationRepository

        actual = CreationRepository.tenant_for_message(resource_id)
    else:
        from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import (
            RuntimeAuditExportRepository,
        )

        actual = RuntimeAuditExportRepository.tenant_for_message(resource_id)
        if actual is not None and _parse_tenant_id(payload_tenant) != actual:
            raise PermissionTaskTenantContextError("export payload disagrees with persistent target")
    if actual is None or (header is not None and _parse_tenant_id(header) != actual):
        raise PermissionTaskTenantContextError("workload tenant proof missing or conflicting")
    from bisheng.common.request_scope import admitted_request_scope

    proof_token = admitted_request_scope.set(None)
    try:
        with tenant_execution_scope(_parse_tenant_id(actual)):
            yield actual
    finally:
        admitted_request_scope.reset(proof_token)


def inject_tenant_header(sender=None, headers=None, **kwargs):
    """Write current tenant_id into Celery task headers before publishing."""
    tid = get_current_tenant_id()
    permission_task = _is_permission_task(sender, headers) or _is_copy_task(sender)
    tenant_task = permission_task or _task_name(sender) in _WORKFLOW_TASKS or _task_name(sender) == _EXPORT_TASK
    if tenant_task and (tid is None or headers is None):
        raise PermissionTaskTenantContextError("permission task publish requires an explicit tenant context")
    if tid is not None and headers is not None:
        headers["tenant_id"] = _parse_tenant_id(tid)
        if permission_task:
            headers["f048_permission_task"] = True


def restore_tenant_context(sender=None, **kwargs):
    """Restore tenant_id ContextVar from task headers on worker side."""
    request = sender.request
    headers = getattr(request, "headers", None) or {}
    # No tenant-scoped SQL may run before the exact resource/job proof.
    request._bisheng_initial_tenant_token = current_tenant_id.set(None)
    tenant_id = _durable_task_tenant(sender, headers.get("tenant_id"))
    permission_task = _is_permission_task(sender, headers) or _is_copy_task(sender)
    if permission_task:
        current_tenant_id.set(None)
        if tenant_id is None:
            raise PermissionTaskTenantContextError("permission task execution requires tenant_id header")
        token = set_current_tenant_id(_parse_tenant_id(tenant_id))
    elif tenant_id is not None:
        token = set_current_tenant_id(_parse_tenant_id(tenant_id))
    else:
        token = set_current_tenant_id(DEFAULT_TENANT_ID)
    request._bisheng_copy_context_token = trusted_copy_tenant.set(
        _parse_tenant_id(tenant_id) if _is_copy_task(sender) else None
    )
    request._bisheng_tenant_context_token = token
    task_id = getattr(request, "id", None)

    # Celery's task stack is thread-local, while async work uses the existing
    # persistent loop. Validate the actual executor at issuance, then retain
    # this request's lifecycle state across copied ContextVars until postrun.
    live = {"active": True}
    request._bisheng_background_task_live = live

    def is_current():
        return live["active"] and request.id == task_id and getattr(request, "called_directly", True) is False

    active = current_task._get_current_object()
    if (
        tenant_id is not None
        and isinstance(task_id, str)
        and task_id
        and active is sender
        and active.request is request
        and is_current()
    ):
        proof = bind_background_task(_parse_tenant_id(tenant_id), task_id, _task_name(sender), is_current=is_current)
    else:
        proof = clear_background_task()
    request._bisheng_background_task_token = proof


def reset_tenant_context(sender=None, **kwargs):
    """Reset tenant_id ContextVar after task execution.

    Prevents tenant context from leaking when Celery reuses threads.
    """
    request = getattr(sender, "request", None)
    copy_token = getattr(request, "_bisheng_copy_context_token", None)
    if copy_token is not None:
        try:
            trusted_copy_tenant.reset(copy_token)
        except (LookupError, RuntimeError, TypeError, ValueError):
            trusted_copy_tenant.set(None)
        finally:
            request._bisheng_copy_context_token = None
    else:
        trusted_copy_tenant.set(None)
    live = getattr(request, "_bisheng_background_task_live", None)
    if live is not None:
        live["active"] = False
        request._bisheng_background_task_live = None
    proof = getattr(request, "_bisheng_background_task_token", None)
    if proof is not None:
        reset_background_task(proof)
        request._bisheng_background_task_token = None
    else:
        clear_background_task()
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
    initial = getattr(request, "_bisheng_initial_tenant_token", None)
    if initial is not None:
        try:
            current_tenant_id.reset(initial)
        except (LookupError, RuntimeError, TypeError, ValueError):
            current_tenant_id.set(None)
        finally:
            request._bisheng_initial_tenant_token = None


# Register after defining the handlers so direct unit tests still exercise the
# real functions when Celery signals are replaced with import-time test stubs.
before_task_publish.connect(inject_tenant_header)
task_prerun.connect(restore_tenant_context)
task_postrun.connect(reset_tenant_context)
