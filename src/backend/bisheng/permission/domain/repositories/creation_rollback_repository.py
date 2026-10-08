"""Remove creation mirrors only after their durable rollback has finalized."""

from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class CreationRollbackRepository(ProjectionRepository):
    async def purge(self, target: VerifiedPermissionTarget, operation_id: int) -> None:
        """Keep the operation ledger for audit/retry; remove only live mirrors."""
        async with self._session(write=True) as session:
            operation = (
                (
                    await session.execute(
                        select(PermissionProjectionOperation).where(
                            PermissionProjectionOperation.tenant_id == target.tenant_id,
                            PermissionProjectionOperation.id == operation_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if (
                operation is None
                or operation.status != "FINALIZED"
                or operation.operation_type != "RESOURCE_CREATE_ROLLBACK"
                or operation.scope_key != f"{target.resource_type}:{target.resource_id}"
            ):
                raise PermissionVersionConflictError(msg="Creation rollback has not finalized")
            mode = (
                (
                    await session.execute(
                        select(ResourcePermissionMode)
                        .where(
                            ResourcePermissionMode.tenant_id == target.tenant_id,
                            ResourcePermissionMode.resource_type == target.resource_type,
                            ResourcePermissionMode.resource_id == target.resource_id,
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if mode is None:
                return
            if (
                mode.operation_id != operation_id
                or mode.version != operation.target_version
                or mode.projection_state != "CURRENT"
            ):
                raise PermissionVersionConflictError(msg="Creation rollback scope changed before cleanup")
            grant_ids = select(PermissionGrant.id).where(
                PermissionGrant.tenant_id == target.tenant_id,
                PermissionGrant.resource_type == target.resource_type,
                PermissionGrant.resource_id == target.resource_id,
            )
            await session.execute(
                delete(PermissionGrantAssignee).where(
                    PermissionGrantAssignee.tenant_id == target.tenant_id,
                    PermissionGrantAssignee.grant_id.in_(grant_ids),
                )
            )
            for model in (PermissionVisibleSourceProjection, PermissionGrant, ResourcePermissionMode):
                await session.execute(
                    delete(model).where(
                        model.tenant_id == target.tenant_id,
                        model.resource_type == target.resource_type,
                        model.resource_id == target.resource_id,
                    )
                )
