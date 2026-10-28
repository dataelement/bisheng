"""Eligibility of frozen releases, separate from the service account's later owner."""

from loguru import logger

from bisheng.app_publish.domain.repositories.release_tenancy_repository import ReleaseTenancyRepository
from bisheng.app_publish.domain.schemas.release_tenancy import ApprovedReleaseSource
from bisheng.approval.application.execution_source import get_business_approval
from bisheng.common.errcode.app_publish import AppVersionNotFoundError
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.open_api import OpenApiAuthDependencyUnavailableError
from bisheng.open_api.application.service_account_tenancy import require_owner_tenant

_APPROVED_DECISION_STATES = frozenset({"approved", "executing", "executed", "execute_failed"})


def _invalid_source():
    return AppVersionNotFoundError(details={"reason": "release_source_invalid"})


async def require_release_eligible(app_id: str, *, version_id: str | None = None, deployment_id: str | None = None):
    try:
        rows = await ReleaseTenancyRepository.load(app_id, version_id=version_id, deployment_id=deployment_id)
        if rows is None:
            raise _invalid_source()
        app, deployment, version = rows.app, rows.deployment, rows.version
        if (
            app.id != app_id
            or app.state == "deleted"
            or deployment.app_id != app.id
            or deployment.tenant_id != app.tenant_id
            or deployment.owner_user_id != app.owner_user_id
            or (deployment_id is not None and deployment.id != deployment_id)
            or (
                version_id is not None
                and (
                    version is None
                    or version.id != version_id
                    or version.app_id != app_id
                    or deployment.version_id != version_id
                )
            )
        ):
            raise _invalid_source()
        await require_owner_tenant(deployment.owner_user_id, deployment.tenant_id)
        return rows
    except BaseErrorCode:
        raise
    except Exception as exc:
        logger.opt(exception=True).warning("app_publish release eligibility dependency failed")
        raise OpenApiAuthDependencyUnavailableError() from exc


async def qualify_approved_release(instance_id: int, payload_snapshot: dict) -> ApprovedReleaseSource:
    try:
        app_id = str(payload_snapshot.get("app_id") or "")
        version_id = str(payload_snapshot.get("version_id") or "")
        deployment_id = str(payload_snapshot.get("deployment_id") or "")
        if not app_id or not version_id or not deployment_id:
            raise _invalid_source()
        rows = await require_release_eligible(app_id, version_id=version_id, deployment_id=deployment_id)
        approval = await get_business_approval(instance_id)
        if approval is None or (
            approval.id != instance_id
            or approval.scenario_code != "app_publish_request"
            or approval.business_resource_type != "app"
            or approval.business_resource_id != app_id
            or approval.business_key != deployment_id
            or approval.tenant_id != rows.app.tenant_id
            or approval.applicant_user_id != rows.deployment.owner_user_id
            or rows.deployment.approval_instance_id != instance_id
            or approval.status not in _APPROVED_DECISION_STATES
        ):
            raise _invalid_source()
        expected = {
            "app_id": app_id,
            "version_id": version_id,
            "deployment_id": deployment_id,
            "tenant_id": rows.deployment.tenant_id,
            "owner_user_id": rows.deployment.owner_user_id,
        }
        if any(
            payload_snapshot.get(key) != value or approval.payload_snapshot.get(key) != value
            for key, value in expected.items()
        ):
            raise _invalid_source()
        return ApprovedReleaseSource(
            approval_instance_id=instance_id,
            deployment_id=deployment_id,
            app_id=app_id,
            version_id=version_id,
            tenant_id=rows.deployment.tenant_id,
            owner_user_id=rows.deployment.owner_user_id,
        )
    except BaseErrorCode:
        raise
    except Exception as exc:
        logger.opt(exception=True).warning("app_publish approval source dependency failed")
        raise OpenApiAuthDependencyUnavailableError() from exc
