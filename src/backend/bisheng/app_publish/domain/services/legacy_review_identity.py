"""Legacy review exclusion is derived from a fully bound original deployment.

Before F114, CLI admission required credential resource-owner == app owner.
It persisted that owner and used them as the approval applicant. This proof
does not reconstruct runtime authorization or permit executing an old release.
"""

from bisheng.app_publish.domain.repositories.release_tenancy_repository import ReleaseTenancyRepository
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter


async def frozen_legacy_review_user(*, instance_id, tenant_id, applicant_user_id, business_resource_id, payload):
    if "self_review_user_id" in payload or "submission_actor" in payload:
        return None  # Modern, incomplete snapshots must never use legacy recovery.
    owner = payload.get("owner_user_id")
    if (
        type(instance_id) is not int
        or instance_id <= 0
        or type(owner) is not int
        or owner <= 0
        or owner != applicant_user_id
        or payload.get("tenant_id") != tenant_id
        or get_current_tenant_id() != tenant_id
        or payload.get("app_id") != business_resource_id
        or payload.get("source") != "cli"
        or not payload.get("version_id")
        or not payload.get("deployment_id")
    ):
        return None
    with strict_tenant_filter():
        records = await ReleaseTenancyRepository.load(
            business_resource_id, version_id=payload["version_id"], deployment_id=payload["deployment_id"]
        )
    if records is None:
        return None
    deployment = records.deployment
    if (
        records.app.tenant_id != tenant_id
        or deployment.tenant_id != tenant_id
        or deployment.approval_instance_id != instance_id
        or deployment.owner_user_id != owner
        or deployment.authorization_context is not None
        or type(deployment.submitted_by_user_id) is not int
        or deployment.submitted_by_user_id not in {0, owner}
        or records.version is None
        or records.version.id != payload["version_id"]
        or records.version.version_no != payload.get("version_no")
    ):
        return None
    return owner
