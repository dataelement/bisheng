"""Approval information for an already-authorized application's versions."""

from bisheng.app_publish.domain.repositories.version_review_repository import VersionReviewRepository
from bisheng.approval.application.execution_source import get_business_approvals
from bisheng.common.errcode.app_factory import AppStateConflictError


async def version_approval_states(app_id: str, tenant_id: int, version_ids: list[str]) -> dict[str, str]:
    deployments = await VersionReviewRepository.deployments(app_id, tenant_id, version_ids)
    approvals = await get_business_approvals([d.approval_instance_id for d in deployments if d.approval_instance_id])
    return {
        deployment.version_id: approval.status
        for deployment in deployments
        if (approval := approvals.get(deployment.approval_instance_id)) is not None
        and approval.tenant_id == tenant_id
        and approval.scenario_code == "app_publish_request"
        and approval.business_resource_type == "app"
        and approval.business_resource_id == app_id
        and approval.business_key == deployment.id
    }


async def refuse_unapproved_start(app_id: str) -> None:
    """Explain a missing runnable version without authorizing any deployment."""
    latest = await VersionReviewRepository.latest(app_id)
    approvals = await get_business_approvals(
        [latest.approval_instance_id] if latest and latest.approval_instance_id else []
    )
    approval = approvals.get(latest.approval_instance_id) if latest else None
    reason = "no_approved_version"
    if (
        approval is not None
        and approval.tenant_id == latest.tenant_id
        and approval.business_resource_type == "app"
        and approval.business_resource_id == app_id
        and approval.business_key == latest.id
        and approval.scenario_code == "app_publish_request"
    ):
        reason = {
            "pending": "approval_pending",
            "rejected": "approval_rejected",
            "withdrawn": "approval_withdrawn",
            "cancelled": "approval_cancelled",
            "exception": "approval_exception",
            "approved": "approval_executing",
            "executing": "approval_executing",
            "execute_failed": "approval_execute_failed",
        }.get(approval.status, reason)
    elif latest is not None:
        reason = "publish_failed" if latest.status == "failed" else "publish_preparing"
    messages = {
        "no_approved_version": "No approved version is available. Submit a release with bisheng deploy first.",
        "approval_pending": "Release approval is pending. Wait for approval before going online.",
        "approval_rejected": "Release approval was rejected. Review the reason and resubmit with bisheng deploy.",
        "approval_withdrawn": "Release approval was withdrawn. Resubmit with bisheng deploy.",
        "approval_cancelled": "Release approval was cancelled. Resubmit with bisheng deploy.",
        "approval_exception": "Release approval needs administrator attention in the approval center.",
        "approval_executing": "Approval passed; deployment is being prepared. Refresh the release status shortly.",
        "approval_execute_failed": "Approval execution failed. Ask an administrator to review and retry it.",
        "publish_failed": "Release preparation failed. Review the failure and resubmit.",
        "publish_preparing": "Release preparation is in progress. Refresh the release status shortly.",
    }
    raise AppStateConflictError(msg=messages[reason], app_id=app_id, reason=reason)
