from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)


class ResourceUserInviteRequestRepository:
    """Session-bound persistence for Permission-owned invite facts."""

    _PENDING_PROJECTION_STATES = (
        ResourceUserInviteExecutionState.AWAITING_APPROVAL,
        ResourceUserInviteExecutionState.QUEUED,
        ResourceUserInviteExecutionState.APPLYING,
        ResourceUserInviteExecutionState.FAILED,
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(
        self,
        *,
        tenant_id: int,
        business_key: str,
        for_update: bool = False,
    ) -> ResourceUserInviteRequest | None:
        statement = select(ResourceUserInviteRequest).where(
            ResourceUserInviteRequest.tenant_id == int(tenant_id),
            ResourceUserInviteRequest.business_key == business_key,
            ResourceUserInviteRequest.active_marker == 0,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def add_and_flush(self, row: ResourceUserInviteRequest) -> ResourceUserInviteRequest:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_id(
        self,
        *,
        tenant_id: int,
        request_id: int,
        for_update: bool = False,
    ) -> ResourceUserInviteRequest | None:
        statement = select(ResourceUserInviteRequest).where(
            ResourceUserInviteRequest.tenant_id == int(tenant_id),
            ResourceUserInviteRequest.id == int(request_id),
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def bind_approval_instance(
        self,
        row: ResourceUserInviteRequest,
        *,
        approval_instance_id: int,
    ) -> None:
        row.approval_instance_id = int(approval_instance_id)
        self.session.add(row)
        await self.session.flush()

    async def list_pending_for_resource(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
    ) -> list[ResourceUserInviteRequest]:
        statement = (
            select(ResourceUserInviteRequest)
            .where(
                ResourceUserInviteRequest.tenant_id == int(tenant_id),
                ResourceUserInviteRequest.resource_type == resource_type,
                ResourceUserInviteRequest.resource_id == resource_id,
                ResourceUserInviteRequest.active_marker == 0,
                ResourceUserInviteRequest.execution_state.in_(self._PENDING_PROJECTION_STATES),
            )
            .order_by(ResourceUserInviteRequest.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
