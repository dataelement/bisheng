"""Regression: telemetry ``log_event_sync`` must propagate the tenant
ContextVar into its worker thread.

Without ``copy_context()`` at submit time, ``ThreadPoolExecutor`` workers
inherit no Context, and the SQLAlchemy ``tenant_filter`` raises
``NoTenantContextError`` under ``multi_tenant.enabled=True`` (observed in
the field when querying the user-with-groups eager load).

This test bypasses ``conftest.premock_import_chain``'s blanket mock of
the telemetry module so we can exercise the real ``log_event_sync`` code
path. Optional native deps (elasticsearch) are stubbed in ``sys.modules``
before the real module is loaded.
"""

import sys
from unittest.mock import MagicMock

# Stub native deps the real telemetry module imports at top level. Must run
# before we drop the conftest pre-mock and reload the real module.
for _mod in ('elasticsearch', 'elasticsearch.exceptions'):
    if _mod not in sys.modules or isinstance(sys.modules[_mod], MagicMock):
        sys.modules.setdefault(_mod, MagicMock())

# Drop the conftest pre-mock so the real module gets loaded by the import
# below. Both the parent package and the leaf module are pre-mocked.
for _mod in (
    'bisheng.common.services.telemetry.telemetry_service',
    'bisheng.common.services.telemetry',
    'bisheng.common.services',
):
    sys.modules.pop(_mod, None)

import threading  # noqa: E402

from bisheng.common.constants.enums.telemetry import (  # noqa: E402
    BaseTelemetryTypeEnum,
)
from bisheng.common.schemas.telemetry.base_telemetry_schema import (  # noqa: E402
    UserContext,
)
from bisheng.common.services.telemetry.telemetry_service import (  # noqa: E402
    BaseTelemetryService,
)
from bisheng.core.context.tenant import (  # noqa: E402
    current_tenant_id,
    set_current_tenant_id,
)


def _build_service() -> BaseTelemetryService:
    """Service with ES short-circuited so ``log_event_sync`` skips network
    IO and exercises only the threading + ContextVar path."""
    service = BaseTelemetryService()
    service._es_client_sync = MagicMock()
    service._index_initialized = True
    return service


def _capture_futures(service):
    """Wrap ``thread_pool.submit`` so the test can ``future.result(...)``
    and surface worker exceptions (otherwise swallowed by the worker's
    own try/except)."""
    captured = []
    real_submit = service.thread_pool.submit

    def tracking_submit(*args, **kwargs):
        f = real_submit(*args, **kwargs)
        captured.append(f)
        return f

    service.thread_pool.submit = tracking_submit
    return captured


def test_log_event_sync_propagates_tenant_to_worker_thread():
    """Worker thread must observe the caller's tenant_id ContextVar."""
    captured = {}

    def fake_init(user_id):
        captured['tenant_id'] = current_tenant_id.get()
        captured['thread_name'] = threading.current_thread().name
        return UserContext(user_id=user_id, user_name=str(user_id))

    service = _build_service()
    service._init_user_context_sync = fake_init
    futures = _capture_futures(service)
    main_thread_name = threading.current_thread().name

    token = set_current_tenant_id(42)
    try:
        service.log_event_sync(
            user_id=1,
            event_type=BaseTelemetryTypeEnum.USER_LOGIN,
            trace_id='trace-propagate',
        )
    finally:
        current_tenant_id.reset(token)

    assert futures, 'log_event_sync did not submit to thread_pool'
    futures[0].result(timeout=5)  # surfaces worker exceptions

    assert captured.get('tenant_id') == 42, (
        f"worker saw tenant_id={captured.get('tenant_id')}, expected 42 — "
        'copy_context propagation is broken'
    )
    assert captured.get('thread_name') != main_thread_name, (
        'worker ran on the main thread; cross-thread propagation untested'
    )


def test_log_event_sync_isolates_worker_context_mutations():
    """ContextVar writes inside the worker must not leak back to the caller.

    ``copy_context()`` returns a Context snapshot; ``ctx.run`` operates on
    that snapshot. A worker that ``set_current_tenant_id(...)`` mutates
    only the snapshot, leaving the calling thread's ContextVar untouched.
    """
    def fake_init(user_id):
        set_current_tenant_id(999)  # tamper inside the worker thread
        return UserContext(user_id=user_id, user_name=str(user_id))

    service = _build_service()
    service._init_user_context_sync = fake_init
    futures = _capture_futures(service)

    token = set_current_tenant_id(7)
    try:
        service.log_event_sync(
            user_id=1,
            event_type=BaseTelemetryTypeEnum.USER_LOGIN,
            trace_id='trace-isolate',
        )
        assert futures, 'log_event_sync did not submit to thread_pool'
        futures[0].result(timeout=5)
        assert current_tenant_id.get() == 7, (
            'worker mutation leaked into calling thread ContextVar'
        )
    finally:
        current_tenant_id.reset(token)
