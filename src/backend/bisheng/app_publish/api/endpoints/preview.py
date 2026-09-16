"""``/api/v1/apps/{app_id}/versions/{version_id}/preview`` — the approver's trial run (AC-26 … AC-29 / T053).

Three calls, session-authenticated, consumed by the client's review view:

* ``GET  …/preview`` — this approver's own trial, if there is one, plus whether
  one is possible at all. The panel's four states come from ``state`` +
  ``runnable``.
* ``POST …/preview`` — raise one. Returns the same shape; a trial that is
  already running is returned unchanged rather than replaced.
* ``DELETE …/preview/{session_id}`` — 「手动回收」.

Every refusal — not an approver of this version, a version with no build, a
session that is already gone, an orchestrator that would not start it — rides
in the 200 envelope as a business code (16264 / 16265 / 16266 / 16267). The
client's approval centre is a panel inside the settings page: a real 403 would
navigate the whole SPA to ``/403`` and take the approver off the request they
were deciding (design K11 ②).

There is deliberately **no endpoint that lists other people's previews**. A
preview carries the identity of the approver it was raised for (AC-27), so
"whose trial is this" is never a question the client has to ask.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/apps", tags=["HostedAppPreview"])


@router.get(
    "/{app_id}/versions/{version_id}/preview",
    response_model=UnifiedResponseModel[dict],
    summary="This approver's temporary preview instance of one version",
)
async def get_preview(
    app_id: str,
    version_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """``{state, session_id, entry_url, expires_at, reclaim_reason, runnable, not_runnable_reason}``."""
    return resp_200(data=await PreviewInstanceService.describe(app_id, version_id, actor=user))


@router.post(
    "/{app_id}/versions/{version_id}/preview",
    response_model=UnifiedResponseModel[dict],
    summary="Raise a temporary preview instance of the version waiting to go live",
)
async def start_preview(
    app_id: str,
    version_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """AC-26. Same shape as the read; ``entry_url`` is what 「打开预览」 opens."""
    return resp_200(data=await PreviewInstanceService.start(app_id, version_id, actor=user))


@router.delete(
    "/{app_id}/versions/{version_id}/preview/{session_id}",
    response_model=UnifiedResponseModel[dict],
    summary="Reclaim one's own preview instance",
)
async def reclaim_preview(
    app_id: str,
    version_id: str,
    session_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """AC-26/AC-28 — 「手动回收」. ``version_id`` is in the path for symmetry only:
    the session row is the authority on which version it belongs to, and
    trusting the path instead would let a caller reclaim a session by naming a
    version they happen to be an approver of."""
    return resp_200(data=await PreviewInstanceService.reclaim(app_id, session_id, actor=user))
