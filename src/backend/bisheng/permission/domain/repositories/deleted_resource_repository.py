"""Purge rebuildable permission mirrors, retaining the deletion journals."""

from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository


class DeletedResourceRepository(ProjectionRepository):
    @staticmethod
    def scope(model, target):
        return (
            model.tenant_id == target.tenant_id,
            model.resource_type == target.resource_type,
            model.resource_id == target.resource_id,
        )

    async def snapshot(self, target):
        async with self._session() as session:
            mode = (
                await session.exec(select(ResourcePermissionMode).where(*self.scope(ResourcePermissionMode, target)))
            ).one_or_none()
            grants = tuple(
                (
                    await session.exec(
                        select(PermissionGrant).where(*self.scope(PermissionGrant, target)).order_by(PermissionGrant.id)
                    )
                ).all()
            )
            visible = tuple(
                (
                    await session.exec(
                        select(PermissionVisibleSourceProjection).where(
                            *self.scope(PermissionVisibleSourceProjection, target)
                        )
                    )
                ).all()
            )
            if mode is None and (grants or visible):
                raise PermissionVersionConflictError(msg="Deleted resource has mirrors without a permission fence")
            return mode, grants

    async def purge(self, target, operation):
        """The owner has committed business deletion and verified FGA is empty."""
        if (
            operation.tenant_id != target.tenant_id
            or operation.scope_type != "resource"
            or operation.scope_key != f"{target.resource_type}:{target.resource_id}"
            or operation.operation_type not in {"RESOURCE_DELETE", "RESOURCE_DELETE_PURGE"}
            or operation.status != "FINALIZED"
        ):
            raise PermissionVersionConflictError(msg="A finalized deletion receipt is required")
        async with self._session(write=True) as session:
            mode = (
                await session.exec(
                    select(ResourcePermissionMode).where(*self.scope(ResourcePermissionMode, target)).with_for_update()
                )
            ).one_or_none()
            if mode is None:
                for model in (PermissionGrant, PermissionVisibleSourceProjection):
                    if (
                        await session.exec(select(model.id).where(*self.scope(model, target)).limit(1))
                    ).first() is not None:
                        raise PermissionVersionConflictError(msg="Deleted-resource mirrors lost their permission fence")
                return
            if (
                mode.operation_id != operation.id
                or mode.version != operation.target_version
                or mode.projection_state != "CURRENT"
            ):
                raise PermissionVersionConflictError(msg="Deleted resource permission intent changed")
            # Explicit tenant predicates are required on bulk Core deletes.
            grants = select(PermissionGrant.id).where(*self.scope(PermissionGrant, target))
            await session.exec(
                delete(PermissionGrantAssignee).where(
                    PermissionGrantAssignee.tenant_id == target.tenant_id,
                    PermissionGrantAssignee.grant_id.in_(grants),
                )
            )
            for model in (PermissionVisibleSourceProjection, PermissionGrant, ResourcePermissionMode):
                await session.exec(delete(model).where(*self.scope(model, target)))
