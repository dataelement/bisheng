"""Subject- and target-bound pending review reads, independent of browser scope."""

from sqlmodel import col, select

from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session


class AppReviewRepository:
    @staticmethod
    async def pending_for_viewer(viewer_user_id: int, app_id: str):
        statement = (
            select(ApprovalInstance, ApprovalTask)
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
        # Personal task ownership and exact business target replace page-view scope here.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())
