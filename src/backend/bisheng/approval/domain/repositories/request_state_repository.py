"""Bounded state-only projection for a business applicant's current requests."""

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.core.database import get_async_db_session


async def list_active_request_states(*, scenario_code: str, applicant_user_id: int, business_keys: list[str]):
    if not business_keys:
        return []
    statement = (
        select(ApprovalInstance.business_key, ApprovalInstance.status)
        .where(
            ApprovalInstance.scenario_code == scenario_code,
            ApprovalInstance.applicant_user_id == applicant_user_id,
            ApprovalInstance.business_key.in_(business_keys),
            ApprovalInstance.status.in_(ApprovalInstanceRepository._DUPLICATE_ACTIVE_STATUSES),
        )
        .order_by(ApprovalInstance.id.desc())
    )
    async with get_async_db_session() as session:
        return (await session.exec(statement)).all()
