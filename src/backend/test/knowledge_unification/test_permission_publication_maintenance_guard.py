"""Permission-owned catalog transactions obey the explicit executor fence."""

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, tenant_execution_scope
from bisheng.permission.application.catalog_api import SqlCatalogState
from bisheng.permission.domain.models import PermissionCatalogRelease
from bisheng.permission.domain.services.maintenance_guard import maintenance_guard
from test.permission import test_f048_catalog_runtime as original

session_factory = original.session_factory


async def test_catalog_reservation_checks_fence_inside_its_own_native_transaction(session_factory):
    current = await original._seed_current(session_factory, original.InMemoryCatalogFGA())
    state, seen = SqlCatalogState(session_factory=session_factory), []

    async def reject(session):
        assert session.in_transaction() and get_current_tenant_id() == 101 and not is_tenant_filter_bypassed()
        seen.append(session)
        raise RuntimeError("executor token was superseded")

    args = {
        "base_release_id": current.id,
        "operator_id": 7,
        "idempotency_key": "guarded-reservation",
        "expires_at": datetime.now() + timedelta(minutes=10),
    }
    with tenant_execution_scope(101), maintenance_guard(transaction_guard=reject):
        with pytest.raises(RuntimeError, match="superseded"):
            await state.reserve_draft(**args)
    assert seen
    async with session_factory() as session:
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(PermissionCatalogRelease))
        ).scalar_one() == 1
    with tenant_execution_scope(101):
        reservation = await state.reserve_draft(**args)
    assert reservation.release_id != current.id
