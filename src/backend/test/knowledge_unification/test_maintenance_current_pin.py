"""Maintenance reads the old CURRENT pin without new business admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from test.knowledge_unification.test_prepare_history import history as history
from test.knowledge_unification.test_prepare_history import native as native
from test.knowledge_unification.test_prepare_history import resource_native as resource_native

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.permission.domain.models import PermissionCatalogRelease
from scripts import f048_maintenance_runtime as maintenance
from scripts import prepare_f118_history as preparation


async def test_maintenance_uses_original_current_and_rechecks_pin_before_native_calls(history, monkeypatch):
    import bisheng.core.database as database

    async with preparation.global_session(history.sessions) as session:
        pin = await preparation.read_pin(session)
    client = SimpleNamespace(store_id=pin["store_id"], model_id=pin["model_id"])
    monkeypatch.setattr(database, "get_async_db_session", history.sessions)
    monkeypatch.setattr(maintenance, "_client", client)
    monkeypatch.setattr(maintenance, "_pin", pin)
    assert await maintenance.maintenance_client() is client
    finalizer = SimpleNamespace(finalize=AsyncMock())
    port = maintenance._PinnedPort(finalizer)
    await port.finalize("original-plan", 1)
    async with preparation.global_session(history.sessions) as session:
        await session.exec(sa.update(PermissionCatalogRelease).values(checksum="f" * 64))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await port.finalize("original-plan", 1)
    finalizer.finalize.assert_awaited_once_with("original-plan", 1)


@pytest.mark.parametrize(
    "status,operation_type,deleted,reason",
    [
        ("FINALIZED", "RESOURCE_DELETE", False, "unification_inventory_business_delete_not_committed"),
        ("COMMITTED", "GRANT_MUTATION", False, "unification_inventory_business_marker_operation_not_finalized"),
        ("FINALIZED", "GRANT_MUTATION", False, None),
        ("FINALIZED", "RESOURCE_DELETE", True, None),
    ],
)
async def test_marker_recovery_never_overrides_a_delete_or_unfinished_intent(
    history, status, operation_type, deleted, reason
):
    from bisheng.database.models.flow import Flow
    from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
    from bisheng.permission.domain.models import PermissionProjectionOperation

    async with preparation.global_session(history.sessions) as session:
        session.add(
            Flow(id="marker-owner", tenant_id=101, user_id=7, name="owner", flow_type=10, is_delete=int(deleted))
        )
        session.add(
            PermissionProjectionOperation(
                id=7001,
                tenant_id=101,
                idempotency_key="marker-intent",
                request_checksum="a" * 64,
                operation_type=operation_type,
                scope_type="resource",
                scope_key="workflow:marker-owner",
                expected_version=1,
                target_version=2,
                store_id="store",
                model_id="model",
                status=status,
                before_checksum="b" * 64,
                after_checksum="c" * 64,
                operator_id=7,
            )
        )
    async with history.sessions() as session, session.begin():

        async def inspect():
            return await UnificationInventoryRepository().ainspect_permission_resource_liveness(
                session, resources=(("workflow", "marker-owner"),), operations={("workflow", "marker-owner"): (7001, 2)}
            )

        if reason:
            with pytest.raises(KnowledgeOperationPlanConflictError) as error:
                await inspect()
            assert error.value.kwargs["reason"] == reason
        else:
            assert await inspect() == {("workflow", "marker-owner"): not deleted}
