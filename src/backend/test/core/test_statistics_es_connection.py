"""Regression tests for statistics ES lazy registration in Celery workers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.context.manager import app_context
from bisheng.core.search.elasticsearch import manager as es_manager


@pytest.mark.asyncio
async def test_get_statistics_es_connection_lazy_registers_with_ssl_verify():
    """Celery workers do not run full app_context init; lazy path must use ssl_verify."""
    registry = app_context._registry
    if es_manager.statistics_es_name in registry.get_all_contexts():
        registry.unregister(es_manager.statistics_es_name)

    fake_conn = MagicMock()
    fake_conn.es_connection = AsyncMock()

    with patch.object(es_manager.EsConnManager, "_async_initialize", return_value=fake_conn):
        client = await es_manager.get_statistics_es_connection()

    assert client is fake_conn.es_connection
    ctx = app_context.get_context(es_manager.statistics_es_name)
    assert ctx.es_hosts is not None
