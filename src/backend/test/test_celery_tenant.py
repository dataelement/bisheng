"""Tests for Celery tenant context propagation signals.

Tests the signal handler functions directly (without a real Celery broker).
Covers AC-09.
"""

import importlib.util
import sys
from unittest.mock import MagicMock

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)


def _load_tenant_context():
    """Load worker/tenant_context.py directly, bypassing worker/__init__.py."""
    import os
    module_path = os.path.join(
        os.path.dirname(__file__), '..', 'bisheng', 'worker', 'tenant_context.py',
    )
    module_path = os.path.abspath(module_path)
    spec = importlib.util.spec_from_file_location('bisheng.worker.tenant_context', module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tc = _load_tenant_context()
inject_tenant_header = _tc.inject_tenant_header
restore_tenant_context = _tc.restore_tenant_context
reset_tenant_context = _tc.reset_tenant_context


class TestInjectTenantHeader:
    """before_task_publish signal: inject tenant_id into headers."""

    def test_inject_tenant_header(self):
        """Should write current tenant_id into headers dict."""
        token = set_current_tenant_id(2)
        try:
            headers = {}
            inject_tenant_header(headers=headers)
            assert headers['tenant_id'] == 2
        finally:
            current_tenant_id.reset(token)

    def test_inject_no_context(self):
        """When no tenant context is set, headers should not be modified."""
        token = current_tenant_id.set(None)
        try:
            headers = {}
            inject_tenant_header(headers=headers)
            assert 'tenant_id' not in headers
        finally:
            current_tenant_id.reset(token)

    def test_inject_none_headers(self):
        """When headers is None (edge case), should not raise."""
        token = set_current_tenant_id(1)
        try:
            inject_tenant_header(headers=None)  # Should not raise
        finally:
            current_tenant_id.reset(token)


class TestRestoreTenantContext:
    """task_prerun signal: restore tenant_id from task headers."""

    def test_restore_tenant_context(self):
        """Should set ContextVar from task request headers."""
        sender = MagicMock()
        sender.request.headers = {'tenant_id': 3}

        restore_tenant_context(sender=sender)

        assert get_current_tenant_id() == 3
        # Cleanup
        current_tenant_id.set(None)

    def test_no_header_uses_default(self):
        """When headers lack tenant_id, should fallback to DEFAULT_TENANT_ID."""
        sender = MagicMock()
        sender.request.headers = {}

        restore_tenant_context(sender=sender)

        assert get_current_tenant_id() == DEFAULT_TENANT_ID
        # Cleanup
        current_tenant_id.set(None)

    def test_none_headers_uses_default(self):
        """When request.headers is None, should fallback to DEFAULT_TENANT_ID."""
        sender = MagicMock()
        sender.request.headers = None

        restore_tenant_context(sender=sender)

        assert get_current_tenant_id() == DEFAULT_TENANT_ID
        # Cleanup
        current_tenant_id.set(None)


class TestResetTenantContext:
    """task_postrun signal: reset ContextVar to prevent thread-pool leakage."""

    def test_postrun_resets_context(self):
        """After task completion, tenant context should be reset to None."""
        set_current_tenant_id(42)

        reset_tenant_context(sender=MagicMock())

        assert get_current_tenant_id() is None
