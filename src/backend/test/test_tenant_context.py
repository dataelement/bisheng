"""Tests for tenant ContextVar and bypass mechanism."""

import asyncio

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    set_current_tenant_id,
)


class TestContextVar:

    def test_default_is_none(self):
        """ContextVar default should be None (no tenant set)."""
        # Reset to ensure clean state
        token = current_tenant_id.set(None)
        try:
            assert get_current_tenant_id() is None
        finally:
            current_tenant_id.reset(token)

    def test_set_get(self):
        """set_current_tenant_id should be readable by get_current_tenant_id."""
        token = set_current_tenant_id(42)
        try:
            assert get_current_tenant_id() == 42
        finally:
            current_tenant_id.reset(token)

    def test_default_tenant_id_constant(self):
        """DEFAULT_TENANT_ID should be 1."""
        assert DEFAULT_TENANT_ID == 1


class TestBypass:

    def test_bypass_context_manager(self):
        """Inside bypass_tenant_filter(), is_bypassed should be True."""
        assert is_tenant_filter_bypassed() is False

        with bypass_tenant_filter():
            assert is_tenant_filter_bypassed() is True

        assert is_tenant_filter_bypassed() is False

    def test_bypass_nested(self):
        """Nested bypass should restore correctly."""
        assert is_tenant_filter_bypassed() is False

        with bypass_tenant_filter():
            assert is_tenant_filter_bypassed() is True

            with bypass_tenant_filter():
                assert is_tenant_filter_bypassed() is True

            # After inner bypass exits, still True (outer bypass active)
            assert is_tenant_filter_bypassed() is True

        # After outer bypass exits, should be False
        assert is_tenant_filter_bypassed() is False


class TestAsyncIsolation:

    def test_async_isolation(self):
        """Different asyncio tasks should have isolated ContextVar values."""
        results = {}

        async def set_and_read(name: str, tenant_id: int):
            set_current_tenant_id(tenant_id)
            # Yield control to let other tasks run
            await asyncio.sleep(0)
            results[name] = get_current_tenant_id()

        async def run():
            t1 = asyncio.create_task(set_and_read('task1', 10))
            t2 = asyncio.create_task(set_and_read('task2', 20))
            await asyncio.gather(t1, t2)

        asyncio.run(run())

        assert results['task1'] == 10
        assert results['task2'] == 20
