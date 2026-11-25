"""Historical purge projection preserves the original unrelated identities."""

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application import unification_identity_retention as policy
from bisheng.knowledge.domain.repositories.unification_history_view_repository import HistoryFactView
from bisheng.permission.domain.models import PermissionProjectionOperation, ResourcePermissionMode
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from test.knowledge_unification import test_unmounted_identity_retention as original

complete, native = original.complete, original.native
raw_resource_native, resource_native = original.raw_resource_native, original.resource_native


async def capture(database, view):
    with tenant_execution_scope(1):
        async with AsyncSession(database.engine) as session, session.begin():
            return await policy.validate(session, repository=PermissionMigrationSnapshotRepository(fact_view=view))


async def test_after_purge_removes_unknown_orphan_without_reclassifying_retained_presets(complete):
    await original.seed(complete)
    expected = await original.observe(complete)
    await complete.insert(
        ResourcePermissionMode,
        [
            {
                "id": 90000,
                "tenant_id": 404,
                "resource_type": "knowledge_file",
                "resource_id": "999",
                "mode": "CUSTOM",
                "projection_state": "CURRENT",
                "version": 1,
            }
        ],
    )
    async with complete.engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    sa.select(ResourcePermissionMode.__table__).where(ResourcePermissionMode.id == 90000)
                )
            )
            .mappings()
            .one()
        )
    with pytest.raises(BaseErrorCode):
        await original.observe(complete)
    view = HistoryFactView()
    try:
        view.replace("resource_permission_mode", dict(row), None)
        before = await original.snapshot(complete)
        assert await capture(complete, view) == expected
        assert await original.snapshot(complete) == before
    finally:
        view.close()


async def test_operation_recovery_is_read_from_after_and_original_pending_stays_in_database(complete):
    await original.seed(complete)
    await complete.insert(
        PermissionProjectionOperation,
        [
            {
                "id": 90001,
                "tenant_id": original.TENANT,
                "idempotency_key": "retained-recovery",
                "request_checksum": "a" * 64,
                "operation_type": "resource_update",
                "scope_type": "resource",
                "scope_key": f"tool:{original.IDENT}",
                "expected_version": 0,
                "target_version": 1,
                "store_id": "store",
                "model_id": "model",
                "status": "PREPARED",
                "before_checksum": "b" * 64,
                "after_checksum": "c" * 64,
                "operator_id": 7,
            }
        ],
    )
    async with complete.engine.begin() as connection:
        await connection.execute(
            sa.update(ResourcePermissionMode)
            .where(ResourcePermissionMode.id == original.IDENT)
            .values(operation_id=90001)
        )
        row = (
            (
                await connection.execute(
                    sa.select(PermissionProjectionOperation.__table__).where(PermissionProjectionOperation.id == 90001)
                )
            )
            .mappings()
            .one()
        )
    with pytest.raises(BaseErrorCode):
        await original.observe(complete)
    view = HistoryFactView()
    try:
        view.replace("permission_projection_operation", dict(row), {**row, "status": "FINALIZED"})
        result = await capture(complete, view)
        assert result.tenant_ids == (original.TENANT,)
        async with complete.engine.connect() as connection:
            assert (
                await connection.execute(
                    sa.select(PermissionProjectionOperation.status).where(PermissionProjectionOperation.id == 90001)
                )
            ).scalar_one() == "PREPARED"
    finally:
        view.close()
