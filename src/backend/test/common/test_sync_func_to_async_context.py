"""Regression: ``bisheng.utils.util.sync_func_to_async`` must preserve
ContextVars when offloading sync work to a thread pool.

``loop.run_in_executor`` does not propagate ``contextvars.Context`` by
default. Under ``multi_tenant.enabled=True`` that causes ORM reads inside
the worker thread to lose ``current_tenant_id`` and fail with
``NoTenantContextError``.
"""

import threading

import pytest

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.utils.util import sync_func_to_async


@pytest.mark.asyncio
async def test_sync_func_to_async_propagates_tenant_context():
    captured = {}
    main_thread_name = threading.current_thread().name

    def task():
        captured['tenant_id'] = current_tenant_id.get()
        captured['thread_name'] = threading.current_thread().name
        return captured['tenant_id']

    token = set_current_tenant_id(42)
    try:
        result = await sync_func_to_async(task)()
    finally:
        current_tenant_id.reset(token)

    assert result == 42
    assert captured.get('tenant_id') == 42
    assert captured.get('thread_name') != main_thread_name


@pytest.mark.asyncio
async def test_sync_func_to_async_isolates_worker_context_mutations():
    def task():
        set_current_tenant_id(999)
        return current_tenant_id.get()

    token = set_current_tenant_id(7)
    try:
        result = await sync_func_to_async(task)()
        assert result == 999
        assert current_tenant_id.get() == 7
    finally:
        current_tenant_id.reset(token)
