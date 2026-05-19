from __future__ import annotations

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import ApprovalException, ApprovalInstance, ApprovalTask
from bisheng.core.database import get_async_db_session


class ApprovalQueryRepository:
    @classmethod
    async def list_instances_by_applicant(cls, tenant_id: int, applicant_user_id: int) -> list[ApprovalInstance]:
        statement = select(ApprovalInstance).where(
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.applicant_user_id == applicant_user_id,
        ).order_by(ApprovalInstance.id.desc())
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def list_tasks_by_approver(cls, tenant_id: int, approver_user_id: int) -> list[ApprovalTask]:
        statement = select(ApprovalTask).where(
            ApprovalTask.tenant_id == tenant_id,
            ApprovalTask.approver_user_id == approver_user_id,
        ).order_by(ApprovalTask.id.desc())
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def list_open_exceptions(cls, tenant_id: int) -> list[ApprovalException]:
        statement = select(ApprovalException).where(
            ApprovalException.tenant_id == tenant_id,
            ApprovalException.status == 'open',
        ).order_by(ApprovalException.id.desc())
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())
