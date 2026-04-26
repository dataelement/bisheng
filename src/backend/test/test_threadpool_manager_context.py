"""Regression: ``bisheng.utils.threadpool.ThreadPoolManager`` sync-path
``submit`` must propagate contextvars (notably the tenant ContextVar)
into the worker thread.

This mirrors the telemetry ``log_event_sync`` fix: the same
``ThreadPoolExecutor`` ContextVar-loss mechanism, but in the project's
shared thread pool used by chat/workflow paths
(``common/chat/client.py``, ``worker/workflow/redis_callback.py``).
Under ``multi_tenant.enabled=True`` the SQLAlchemy tenant_filter
raises ``NoTenantContextError`` whenever such a worker queries a
tenant-aware table.

The async path is intentionally not exercised here: ``asyncio.create_task``
already snapshots ``contextvars.Context``, so the bug never applied to
coroutine submissions.
"""

import threading

from bisheng.core.context.tenant import (
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.utils.threadpool import ThreadPoolManager


def test_submit_sync_propagates_tenant_to_worker_thread():
    """Sync callable submitted to the manager must observe the caller's
    tenant_id ContextVar in the worker thread."""
    tp = ThreadPoolManager(2, thread_name_prefix='test-tp-propagate')
    captured = {}

    def task():
        captured['tenant_id'] = current_tenant_id.get()
        captured['thread_name'] = threading.current_thread().name

    main_thread_name = threading.current_thread().name

    token = set_current_tenant_id(42)
    try:
        future = tp.submit('regression-key', task)
    finally:
        current_tenant_id.reset(token)

    future.result(timeout=5)  # surfaces any worker exception

    assert captured.get('tenant_id') == 42, (
        f"worker saw tenant_id={captured.get('tenant_id')}, expected 42 — "
        'copy_context propagation is broken'
    )
    assert captured.get('thread_name') != main_thread_name, (
        'worker ran on the main thread; cross-thread propagation untested'
    )

    tp.tear_down()


def test_submit_sync_isolates_worker_context_mutations():
    """Worker mutations of ContextVars must not leak back to the calling
    thread. ``ctx.run`` operates on a snapshot, so any
    ``set_current_tenant_id(...)`` inside the worker stays inside that
    snapshot."""
    tp = ThreadPoolManager(2, thread_name_prefix='test-tp-isolate')

    def task():
        set_current_tenant_id(999)  # tamper inside the worker thread

    token = set_current_tenant_id(7)
    try:
        future = tp.submit('regression-key', task)
        future.result(timeout=5)
        assert current_tenant_id.get() == 7, (
            'worker mutation leaked into calling thread ContextVar'
        )
    finally:
        current_tenant_id.reset(token)

    tp.tear_down()


def test_submit_sync_still_sets_trace_id_from_kwarg():
    """The ``context_wrapper`` historically reads ``trace_id`` from kwargs
    and sets ``trace_id_var`` inside the worker. ``ctx.run`` runs on a
    Context copy, so this still works — and the caller's ContextVars
    remain untouched."""
    from bisheng.core.logger import trace_id_var

    tp = ThreadPoolManager(2, thread_name_prefix='test-tp-trace')
    captured = {}

    def task():
        captured['trace_id_in_worker'] = trace_id_var.get()

    main_trace = trace_id_var.get()
    future = tp.submit('regression-key', task, trace_id='custom-trace-xyz')
    future.result(timeout=5)

    assert captured.get('trace_id_in_worker') == 'custom-trace-xyz'
    # Caller's trace_id_var must be unchanged.
    assert trace_id_var.get() == main_trace

    tp.tear_down()
