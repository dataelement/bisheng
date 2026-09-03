"""Dashboard startup initialization must run in the root tenant context."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
    visible_tenant_ids,
)
from bisheng.telemetry_search.domain import init_dataset


class _DatabaseManager:
    async def create_db_and_tables(self) -> None:
        assert get_current_tenant_id() == 1
        assert visible_tenant_ids.get() is None


class _DatasetRepository:
    def __init__(self, session: object) -> None:
        assert session is not None

    async def count(self) -> int:
        assert get_current_tenant_id() == 1
        assert visible_tenant_ids.get() is None
        return 1


async def test_dashboard_startup_uses_root_tenant_and_restores_context(
    monkeypatch,
) -> None:
    async def get_database_connection() -> _DatabaseManager:
        return _DatabaseManager()

    @asynccontextmanager
    async def get_async_db_session() -> AsyncIterator[object]:
        yield object()

    async def upgrade_datasets(repository: _DatasetRepository) -> None:
        assert isinstance(repository, _DatasetRepository)
        assert get_current_tenant_id() == 1

    async def get_dashboards(**kwargs) -> list[object]:
        assert kwargs["dashboard_type"] == [init_dataset.DashboardType.PRESET_OSS]
        assert get_current_tenant_id() == 1
        return [object()]

    monkeypatch.setattr(
        init_dataset,
        "get_database_connection",
        get_database_connection,
    )
    monkeypatch.setattr(
        init_dataset,
        "get_async_db_session",
        get_async_db_session,
    )
    monkeypatch.setattr(
        init_dataset,
        "DashboardDatasetRepositoryImpl",
        _DatasetRepository,
    )
    monkeypatch.setattr(
        init_dataset,
        "_upgrade_datasets_add_department_dimensions",
        upgrade_datasets,
    )
    monkeypatch.setattr(
        init_dataset.DashboardDao,
        "get_dashboards",
        staticmethod(get_dashboards),
    )

    outer_token = set_current_tenant_id(9)
    visible_token = visible_tenant_ids.set(frozenset({9}))
    try:
        await init_dataset.init_dashboard_datasets()
        assert get_current_tenant_id() == 9
        assert visible_tenant_ids.get() == frozenset({9})
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(outer_token)
