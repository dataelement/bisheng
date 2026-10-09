"""SQL rollback cleanup is finalized, fenced, tenant-scoped and idempotent."""

import pytest
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.creation_rollback_repository import CreationRollbackRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from test.permission.test_f048_projection_sql_runtime import _seed_projecting_state
from test.permission.test_f048_projection_sql_runtime import session_factory as session_factory
from test.permission.test_f048_projection_sql_runtime import tenant_context as tenant_context


def _target():
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        resource_version=0,
        parent_type="knowledge_space",
        parent_id="42",
        context_version="created",
    )


async def test_cleanup_removes_live_mirrors_but_keeps_ledger_and_other_tenants(session_factory):
    operation_id = await _seed_projecting_state(session_factory)
    with bypass_tenant_filter():
        async with session_factory() as session:
            async with session.begin():
                operation = await session.get(PermissionProjectionOperation, operation_id)
                operation.operation_type = "RESOURCE_CREATE_ROLLBACK"
                operation.status = "FINALIZED"
                mode = (await session.execute(select(ResourcePermissionMode))).scalars().one()
                mode.version = operation.target_version
                mode.projection_state = "CURRENT"
                session.add(
                    ResourcePermissionMode(
                        tenant_id=8,
                        resource_type="folder",
                        resource_id="42",
                        mode="INHERIT",
                        version=1,
                        projection_state="CURRENT",
                    )
                )
                session.add(
                    PermissionGrant(
                        tenant_id=8,
                        resource_type="folder",
                        resource_id="42",
                        model_key="owner",
                        state="ACTIVE",
                        projection_state="CURRENT",
                    )
                )
    repository = CreationRollbackRepository(session_factory)
    await repository.purge(_target(), operation_id)
    await repository.purge(_target(), operation_id)
    with bypass_tenant_filter():
        async with session_factory() as session:
            for model in (
                PermissionGrantAssignee,
                PermissionVisibleSourceProjection,
                PermissionGrant,
                ResourcePermissionMode,
            ):
                rows = (await session.execute(select(model))).scalars().all()
                assert all(row.tenant_id == 8 for row in rows)
            assert len((await session.execute(select(PermissionGrant))).scalars().all()) == 1
            assert len((await session.execute(select(ResourcePermissionMode))).scalars().all()) == 1
            assert await session.get(PermissionProjectionOperation, operation_id) is not None


async def test_unfinalized_rollback_cannot_purge(session_factory):
    operation_id = await _seed_projecting_state(session_factory)
    with pytest.raises(PermissionVersionConflictError):
        await CreationRollbackRepository(session_factory).purge(_target(), operation_id)
    async with session_factory() as session:
        assert (await session.execute(select(PermissionGrant))).scalars().first() is not None
