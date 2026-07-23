from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
    DepartmentFileViewGrantStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.department_file_view_grant_repository import (
    DepartmentFileViewGrantRepository,
)


class DepartmentFileViewGrantRepositoryImpl(DepartmentFileViewGrantRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _resource_predicate(
        resource_keys: set[tuple[int, int]],
    ):
        return or_(
            *[
                and_(
                    DepartmentFileViewGrant.space_id == space_id,
                    DepartmentFileViewGrant.file_id == file_id,
                )
                for space_id, file_id in sorted(resource_keys)
            ]
        )

    async def list_by_user_and_files(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resource_keys: set[tuple[int, int]],
    ) -> list[DepartmentFileViewGrant]:
        if not resource_keys:
            return []
        statement = select(DepartmentFileViewGrant).where(
            DepartmentFileViewGrant.tenant_id == tenant_id,
            DepartmentFileViewGrant.user_id == user_id,
            self._resource_predicate(resource_keys),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_active_by_user_and_files(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resources: dict[tuple[int, int], int],
    ) -> dict[tuple[int, int], DepartmentFileViewGrant]:
        rows = await self.list_by_user_and_files(
            tenant_id=tenant_id,
            user_id=user_id,
            resource_keys=set(resources),
        )
        return {
            (int(row.space_id), int(row.file_id)): row
            for row in rows
            if row.status == DepartmentFileViewGrantStatus.ACTIVE
            and resources.get((int(row.space_id), int(row.file_id))) == int(row.department_id)
        }

    async def invalidate_stale_active_by_user_and_files(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resources: dict[tuple[int, int], int],
        reason: str,
    ) -> list[DepartmentFileViewGrant]:
        if not resources:
            return []
        statement = (
            select(DepartmentFileViewGrant)
            .where(
                DepartmentFileViewGrant.tenant_id == tenant_id,
                DepartmentFileViewGrant.user_id == user_id,
                DepartmentFileViewGrant.status == DepartmentFileViewGrantStatus.ACTIVE,
                self._resource_predicate(set(resources)),
            )
            .with_for_update()
        )
        result = await self.session.execute(statement)
        rows = [
            row
            for row in result.scalars().all()
            if resources.get((int(row.space_id), int(row.file_id))) != int(row.department_id)
        ]
        now = datetime.now()
        for row in rows:
            row.status = DepartmentFileViewGrantStatus.INVALIDATED
            row.invalidated_at = now
            row.invalidated_reason = reason
            self.session.add(row)
        await self.session.flush()
        return rows

    async def _find_for_update(
        self,
        *,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
    ) -> DepartmentFileViewGrant | None:
        statement = (
            select(DepartmentFileViewGrant)
            .where(
                DepartmentFileViewGrant.tenant_id == tenant_id,
                DepartmentFileViewGrant.user_id == user_id,
                DepartmentFileViewGrant.space_id == space_id,
                DepartmentFileViewGrant.file_id == file_id,
            )
            .with_for_update()
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def activate(
        self,
        *,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        department_id: int,
        approval_instance_id: int,
    ) -> DepartmentFileViewGrant:
        row = await self._find_for_update(
            tenant_id=tenant_id,
            user_id=user_id,
            space_id=space_id,
            file_id=file_id,
        )
        if row is None:
            row = DepartmentFileViewGrant(
                tenant_id=tenant_id,
                user_id=user_id,
                space_id=space_id,
                file_id=file_id,
                department_id=department_id,
                approval_instance_id=approval_instance_id,
                granted_at=datetime.now(),
            )
            self.session.add(row)
            await self.session.flush()

        row.department_id = department_id
        row.approval_instance_id = approval_instance_id
        row.grant_source = "approval_instance"
        row.status = DepartmentFileViewGrantStatus.ACTIVE
        row.granted_at = datetime.now()
        row.revoked_at = None
        row.revoked_by = None
        row.revoked_reason = None
        row.invalidated_at = None
        row.invalidated_reason = None
        self.session.add(row)
        await self.session.flush()
        return row

    async def revoke(
        self,
        *,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        approval_instance_id: int,
        revoked_by: int,
        reason: str,
    ) -> DepartmentFileViewGrant | None:
        row = await self._find_for_update(
            tenant_id=tenant_id,
            user_id=user_id,
            space_id=space_id,
            file_id=file_id,
        )
        if (
            row is None
            or row.status != DepartmentFileViewGrantStatus.ACTIVE
            or int(row.approval_instance_id) != approval_instance_id
        ):
            return None
        row.status = DepartmentFileViewGrantStatus.REVOKED
        row.revoked_at = datetime.now()
        row.revoked_by = revoked_by
        row.revoked_reason = reason
        self.session.add(row)
        await self.session.flush()
        return row

    async def invalidate_by_space(
        self,
        *,
        tenant_id: int,
        space_id: int,
        reason: str,
    ) -> list[DepartmentFileViewGrant]:
        return await self._invalidate(
            tenant_id=tenant_id,
            space_id=space_id,
            file_ids=None,
            reason=reason,
        )

    async def invalidate_by_file_ids(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_ids: set[int],
        reason: str,
    ) -> list[DepartmentFileViewGrant]:
        if not file_ids:
            return []
        return await self._invalidate(
            tenant_id=tenant_id,
            space_id=space_id,
            file_ids=file_ids,
            reason=reason,
        )

    async def _invalidate(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_ids: set[int] | None,
        reason: str,
    ) -> list[DepartmentFileViewGrant]:
        statement = (
            select(DepartmentFileViewGrant)
            .where(
                DepartmentFileViewGrant.tenant_id == tenant_id,
                DepartmentFileViewGrant.space_id == space_id,
                DepartmentFileViewGrant.status == DepartmentFileViewGrantStatus.ACTIVE,
            )
            .with_for_update()
        )
        if file_ids is not None:
            statement = statement.where(DepartmentFileViewGrant.file_id.in_(sorted(file_ids)))
        result = await self.session.execute(statement)
        rows = list(result.scalars().all())
        now = datetime.now()
        for row in rows:
            row.status = DepartmentFileViewGrantStatus.INVALIDATED
            row.invalidated_at = now
            row.invalidated_reason = reason
            self.session.add(row)
        await self.session.flush()
        return rows
