"""Subject- and target-bound pending review reads, independent of browser scope."""

from dataclasses import dataclass

from sqlmodel import col, select

from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session


@dataclass(frozen=True, slots=True)
class _InstanceFact:
    id: int
    tenant_id: int
    status: str
    scenario_code: str
    business_resource_type: str
    business_resource_id: str
    payload_snapshot: dict


@dataclass(frozen=True, slots=True)
class _TaskFact:
    id: int
    tenant_id: int
    status: str
    instance_id: int
    approver_user_id: int


class AppReviewRepository:
    @staticmethod
    async def pending_for_viewer(viewer_user_id: int, app_id: str, *, session=None, for_update=False):
        statement = (
            select(
                ApprovalInstance.id,
                ApprovalInstance.tenant_id,
                ApprovalInstance.status,
                ApprovalInstance.scenario_code,
                ApprovalInstance.business_resource_type,
                ApprovalInstance.business_resource_id,
                ApprovalInstance.payload_snapshot,
                ApprovalTask.id,
                ApprovalTask.tenant_id,
                ApprovalTask.status,
                ApprovalTask.instance_id,
                ApprovalTask.approver_user_id,
            )
            .join(ApprovalTask, ApprovalTask.instance_id == ApprovalInstance.id)
            .where(
                ApprovalTask.approver_user_id == viewer_user_id,
                ApprovalTask.status == "pending",
                ApprovalInstance.status == "pending",
                ApprovalInstance.scenario_code == "app_publish_request",
                ApprovalInstance.business_resource_type == "app",
                ApprovalInstance.business_resource_id == app_id,
                ApprovalTask.tenant_id == ApprovalInstance.tenant_id,
            )
            .order_by(col(ApprovalInstance.id).desc(), col(ApprovalTask.id).desc())
            .limit(100)
        )
        if for_update:
            statement = statement.with_for_update()

        async def read(db):
            # Personal task ownership and exact business target replace page-view
            # scope. Column facts never attach foreign approval ORM to the caller.
            with db.no_autoflush, bypass_tenant_filter():
                rows = (await db.exec(statement)).all()
            return [(_InstanceFact(*row[:7]), _TaskFact(*row[7:])) for row in rows]

        if session is not None:
            return await read(session)
        async with get_async_db_session() as db:
            return await read(db)
