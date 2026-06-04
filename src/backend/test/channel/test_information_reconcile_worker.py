"""F031 — Celery Beat thin wrapper for the daily reconcile (spec §7.1 / AC-12).

`reconcile_all_tenants` enumerates active tenants and runs the per-tenant reconcile under
each tenant's context. It contains no business logic; correctness here is purely about
iterating every tenant and isolating per-tenant failures.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.worker.information.reconcile as reconcile_mod


@pytest.mark.asyncio
async def test_reconcile_all_tenants_iterates_each_tenant():
    """Each active tenant's context is set and reconcile runs once per tenant. (AC-12)"""
    service = SimpleNamespace(
        reconcile_information_subscriptions=AsyncMock(return_value={"to_sub": 0, "to_unsub": 0, "failed": 0})
    )
    tenant_seen: list[int] = []

    @asynccontextmanager
    async def _fake_session():
        yield service

    with patch.object(reconcile_mod, "_active_tenant_ids", new=AsyncMock(return_value=[1, 2, 3])), patch.object(
        reconcile_mod, "_channel_service_session", new=_fake_session
    ), patch.object(reconcile_mod, "set_current_tenant_id", side_effect=lambda t: tenant_seen.append(t)):
        await reconcile_mod._reconcile_all_tenants_async()

    assert tenant_seen == [1, 2, 3]
    assert service.reconcile_information_subscriptions.await_count == 3


@pytest.mark.asyncio
async def test_reconcile_all_tenants_isolates_tenant_failure():
    """One tenant failing does not stop the others. (AC-12)"""
    attempted: list[int] = []

    async def _fake_one(tenant_id: int) -> None:
        attempted.append(tenant_id)
        if tenant_id == 2:
            raise RuntimeError("boom")

    with patch.object(reconcile_mod, "_active_tenant_ids", new=AsyncMock(return_value=[1, 2, 3])), patch.object(
        reconcile_mod, "_reconcile_one_tenant", new=_fake_one
    ):
        await reconcile_mod._reconcile_all_tenants_async()

    assert attempted == [1, 2, 3]
