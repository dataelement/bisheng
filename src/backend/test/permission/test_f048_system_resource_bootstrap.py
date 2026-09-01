"""Business predicates for the fresh-install system-resource inventory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.api.services import f048_system_resource_bootstrap as bootstrap
from bisheng.permission.application.system_resource_reconcile import (
    SystemOwnedReconcileReport,
)
from bisheng.tool.domain.models.gpts_tools import GptsToolsType


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


async def test_inventory_requires_each_business_system_predicate(monkeypatch) -> None:
    tool = GptsToolsType(
        id=6,
        name="Code Interpreter",
        is_preset=1,
        user_id=None,
        tenant_id=1,
        is_delete=0,
    )

    class _Session:
        async def exec(self, statement):
            del statement
            return _Result([tool])

    @asynccontextmanager
    async def bound_factory() -> AsyncIterator[_Session]:
        yield _Session()

    monkeypatch.setattr(bootstrap, "get_async_db_session", bound_factory)

    inventory = await bootstrap.load_system_owned_resource_inventory()

    assert [(item.resource_type, item.resource_id) for item in inventory.resources] == [("tool", "6")]
    assert inventory.invalid == ()


async def test_fresh_install_waits_for_marker_and_projects_inventory(monkeypatch) -> None:
    inventory = bootstrap.SystemOwnedResourceInventory(resources=(), invalid=())
    report = SystemOwnedReconcileReport(mode="apply", before=(), after=())
    marker = SimpleNamespace(wait_until_ready=AsyncMock())
    facade = object()
    monkeypatch.setattr(
        bootstrap,
        "get_f048_process_runtime",
        AsyncMock(return_value=SimpleNamespace(components=SimpleNamespace(marker=marker, facade=facade))),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_system_owned_resource_inventory",
        AsyncMock(return_value=inventory),
    )
    reconcile = AsyncMock(return_value=report)
    monkeypatch.setattr(bootstrap, "reconcile_system_owned_resources", reconcile)

    result = await bootstrap.reconcile_fresh_install_system_resources()

    assert result is report
    marker.wait_until_ready.assert_awaited_once()
    reconcile.assert_awaited_once_with(
        facade,
        (),
        apply=True,
        operator_id=bootstrap.SYSTEM_RESOURCE_BOOTSTRAP_OPERATOR_ID,
    )
