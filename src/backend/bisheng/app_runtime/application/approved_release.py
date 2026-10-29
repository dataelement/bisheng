"""Internal approved-release execution; no HTTP route or human-identity fallback."""

from bisheng.app_publish.application.release_tenancy import ApprovedReleaseSource
from bisheng.app_runtime.domain.services.app_state_service import ActionResult, AppStateService


async def start_approved_release(source: ApprovedReleaseSource) -> ActionResult:
    return await AppStateService.publish_approved(source)
