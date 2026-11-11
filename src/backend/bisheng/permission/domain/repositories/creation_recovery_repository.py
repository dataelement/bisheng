"""Complete creation mirrors only after the exact durable projection finalized."""

from sqlalchemy import update
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


class CreationRecoveryRepository(ProjectionRepository):
    async def has_prepared_owner(self, target, operation_id):
        async with self._session() as session:
            mode = (
                (
                    await session.execute(
                        select(ResourcePermissionMode).where(
                            ResourcePermissionMode.tenant_id == target.tenant_id,
                            ResourcePermissionMode.resource_type == target.resource_type,
                            ResourcePermissionMode.resource_id == target.resource_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if mode is None:
                return False
            if mode.operation_id != operation_id:
                raise PermissionVersionConflictError(msg="Creation fence changed")
            return True

    async def finalize_creation(self, target, operation_id, owner_user_id):
        async with self._session(write=True) as session:
            op = await session.get(PermissionProjectionOperation, operation_id)
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
            if (
                op is None
                or op.tenant_id != target.tenant_id
                or op.status != "FINALIZED"
                or op.operation_type != "RESOURCE_CREATE"
                or op.scope_key != f"{target.resource_type}:{target.resource_id}"
                or mode is None
                or mode.operation_id != operation_id
                or mode.version != 1
                or mode.projection_state != "CURRENT"
            ):
                raise PermissionVersionConflictError()
            grants = (
                (
                    await session.execute(
                        select(PermissionGrant).where(
                            PermissionGrant.tenant_id == target.tenant_id,
                            PermissionGrant.resource_type == target.resource_type,
                            PermissionGrant.resource_id == target.resource_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            owner = next((row for row in grants if row.model_key == "owner"), None)
            if owner is None:
                raise PermissionVersionConflictError(msg="Creation owner mirror is missing")
            assignees = (
                (
                    await session.execute(
                        select(PermissionGrantAssignee).where(
                            PermissionGrantAssignee.tenant_id == target.tenant_id,
                            PermissionGrantAssignee.grant_id == owner.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not any(
                row.subject_type == "user"
                and str(row.subject_id) == str(owner_user_id)
                and row.source_type == "CREATOR"
                for row in assignees
            ):
                raise PermissionVersionConflictError(msg="Creation owner changed")
            ids = [row.id for row in grants]
            await session.execute(
                update(PermissionGrant)
                .where(PermissionGrant.tenant_id == target.tenant_id, PermissionGrant.id.in_(ids))
                .values(state="ACTIVE", projection_state="CURRENT")
            )
            await session.execute(
                update(PermissionGrantAssignee)
                .where(
                    PermissionGrantAssignee.tenant_id == target.tenant_id,
                    PermissionGrantAssignee.grant_id.in_(ids),
                    PermissionGrantAssignee.state == "PENDING",
                )
                .values(state="ACTIVE")
            )
            await session.execute(
                update(PermissionVisibleSourceProjection)
                .where(
                    PermissionVisibleSourceProjection.tenant_id == target.tenant_id,
                    PermissionVisibleSourceProjection.operation_id == operation_id,
                    PermissionVisibleSourceProjection.resource_type == target.resource_type,
                    PermissionVisibleSourceProjection.resource_id == target.resource_id,
                    PermissionVisibleSourceProjection.state == "PENDING",
                )
                .values(state="ACTIVE")
            )
