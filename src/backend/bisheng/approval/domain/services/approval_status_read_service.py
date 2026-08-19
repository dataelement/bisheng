from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.ports.approval_status_reader import ApprovalStatusSnapshot
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ApprovalStatusReadService:
    """Approval-owned batch status projection with no payload exposure."""

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    async def get_statuses(
        self,
        *,
        tenant_id: int,
        approval_instance_ids: Sequence[int],
    ) -> dict[int, ApprovalStatusSnapshot]:
        tenant_id = self._require_tenant(tenant_id)
        instance_ids = self._normalize_instance_ids(approval_instance_ids)
        if not instance_ids:
            return {}
        statement = select(ApprovalInstance.id, ApprovalInstance.status).where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.id.in_(instance_ids),
        )
        async with self.session_factory() as session:
            rows = (await session.execute(statement)).all()
        return {
            int(instance_id): ApprovalStatusSnapshot(
                instance_id=int(instance_id),
                status=str(status),
            )
            for instance_id, status in rows
        }

    @staticmethod
    def _normalize_instance_ids(values: Sequence[int]) -> tuple[int, ...]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("approval instance ids must be positive integers")
            if value not in seen:
                normalized.append(value)
                seen.add(value)
        return tuple(normalized)

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
            raise ValueError("approval status read requires a positive tenant id")
        current = get_current_tenant_id()
        if current is None or int(current) != tenant_id:
            raise ValueError("approval status read requires the matching tenant context")
        return tenant_id


__all__ = ["ApprovalStatusReadService"]
