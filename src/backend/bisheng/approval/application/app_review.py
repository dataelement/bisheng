"""Immutable current-task projections for the application owner's review surface."""

from dataclasses import dataclass

from bisheng.approval.domain.repositories.app_review_repository import AppReviewRepository


@dataclass(frozen=True, slots=True)
class AppReviewGrant:
    tenant_id: int
    app_id: str
    version_id: str
    instance_id: int
    task_id: int


async def pending_app_reviews(viewer_user_id: int, app_id: str, version_ids: set[str]) -> tuple[AppReviewGrant, ...]:
    if type(viewer_user_id) is not int or viewer_user_id <= 0 or not app_id or not version_ids:
        return ()
    result = []
    for instance, task in await AppReviewRepository.pending_for_viewer(viewer_user_id, app_id):
        payload = instance.payload_snapshot if isinstance(instance.payload_snapshot, dict) else {}
        version_id = str(payload.get("version_id") or "")
        if (
            instance.status == task.status == "pending"
            and instance.scenario_code == "app_publish_request"
            and instance.business_resource_type == "app"
            and instance.business_resource_id == app_id
            and task.instance_id == instance.id
            and task.approver_user_id == viewer_user_id
            and task.tenant_id == instance.tenant_id
            and bool(version_id)
        ):
            result.append(AppReviewGrant(instance.tenant_id, app_id, version_id, instance.id, task.id))
    return tuple(result)
