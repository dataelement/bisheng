"""``/api/v1/apps/{app_id}/publish-*`` — the publish face's own two endpoints (design D15 / AC-32 / AC-38).

Session-authenticated, unlike the ``/api/v2`` router next door: these serve the
platform SPA, not the CLI.

Only two endpoints exist here, and what is *absent* is the design:

* **No withdraw endpoint.** Withdrawal goes to the approval centre's existing
  ``POST /api/v1/approval/instances/{id}/withdraw``, which already refuses
  anybody who is not the applicant — and the applicant is the owner (AC-16). A
  second endpoint would be a second place for that rule to be enforced, and
  eventually to disagree.
* **No state-changing publish endpoint.** F054 already owns
  ``POST /api/v1/apps/{id}/actions/manual-publish``. This one wraps the owner-only
  pre-check and the version-record latch around it, so that exactly one layer
  writes ``app.state`` and exactly one writes ``terminal_state``.

Refusals ride inside the 200 envelope. The platform's response interceptor
navigates the whole page to ``/403`` on a real 403 or 404, so a non-owner
opening a colleague's application would lose the detail page rather than see a
read-only block (design 坑 22). Every service under here raises ``BaseErrorCode``
subclasses, which the platform handler wraps into a 200.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/apps", tags=["HostedAppPublish"])


@router.get(
    "/{app_id}/publish-status",
    response_model=UnifiedResponseModel[dict],
    summary="Release state of one hosted application",
)
async def get_publish_status(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    """AC-38 — the single read model, shared with F052's MCP status tool.

    Returns design §4.2 ②: application state and why it is parked, the current
    and pending versions, the last attempt, the approval with its rejection
    reason in full, the tier, and the three ``can`` flags the face renders
    buttons from.
    """
    return resp_200(data=await PublishStatusService.get_publish_status(app_id, actor=user))


@router.post(
    "/{app_id}/publish/manual-publish",
    response_model=UnifiedResponseModel[dict],
    summary="Retry a parked release",
)
async def manual_publish(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    """AC-32 — owner-only, no second approval round, no new version record.

    The state transition itself belongs to F054; this endpoint contributes the
    owner-only pre-check (which the permission runtime cannot express, since it
    short-circuits administrators to ALLOW) and the ``terminal_state`` latch on
    success.
    """
    return resp_200(data=await PublishStatusService.request_manual_publish(app_id, actor=user))
