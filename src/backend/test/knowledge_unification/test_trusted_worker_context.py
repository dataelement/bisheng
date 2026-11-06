"""T557: actual background execution is separate from a tenant-shaped request.

覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-92
The real Celery hooks are called; no broker, network or background worker starts.
"""

from types import SimpleNamespace

import pytest

from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.worker import tenant_context as workers

_CURRENT = [None]


@pytest.fixture(autouse=True)
def active_task(monkeypatch):
    _CURRENT[0] = None
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: _CURRENT[0]))
    yield
    _CURRENT[0] = None


def restore_tenant_context(*, sender):
    _CURRENT[0] = sender
    workers.restore_tenant_context(sender=sender)


def reset_tenant_context(*, sender):
    workers.reset_tenant_context(sender=sender)
    _CURRENT[0] = None


def task(*, tenant=101, task_id="actual-task-id", called_directly=False, headers=True):
    return SimpleNamespace(
        name="bisheng.worker.knowledge.rebuild",
        request=SimpleNamespace(
            id=task_id, called_directly=called_directly, headers={"tenant_id": tenant} if headers else {}
        ),
    )


def test_tenant_scope_alone_never_issues_background_provenance():
    with tenant_execution_scope(101):
        assert get_current_tenant_id() == 101
        assert get_current_background_task() is None


def test_real_hooks_issue_exact_context_then_revoke_it_on_exit():
    sender = task()
    restore_tenant_context(sender=sender)
    try:
        original = get_current_background_task()
        assert original is not None
        assert (original.tenant_id, original.task_id, original.task_name) == (101, "actual-task-id", sender.name)
        assert get_current_background_task() is original
        with tenant_execution_scope(202):
            assert get_current_background_task() is None
        assert get_current_background_task() is original
    finally:
        reset_tenant_context(sender=sender)
    assert get_current_background_task() is None


@pytest.mark.parametrize("values", [dict(headers=False), dict(called_directly=True), dict(task_id=None)])
def test_fallback_root_or_direct_call_is_not_a_worker_permit(values):
    sender = task(**values)
    restore_tenant_context(sender=sender)
    try:
        assert get_current_background_task() is None
    finally:
        reset_tenant_context(sender=sender)


def test_reused_worker_thread_does_not_keep_the_previous_task_object():
    first, second = task(), task(task_id="next-task")
    restore_tenant_context(sender=first)
    original = get_current_background_task()
    reset_tenant_context(sender=first)
    restore_tenant_context(sender=second)
    try:
        assert get_current_background_task() is not original
        assert get_current_background_task().task_id == "next-task"
    finally:
        reset_tenant_context(sender=second)


def test_saved_context_is_not_live_after_actual_task_stack_leaves():
    sender = task()
    restore_tenant_context(sender=sender)
    try:
        assert get_current_background_task() is not None
        _CURRENT[0] = None
        assert get_current_background_task() is None
    finally:
        reset_tenant_context(sender=sender)
