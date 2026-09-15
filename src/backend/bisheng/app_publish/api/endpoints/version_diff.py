"""``GET /api/v1/apps/{app_id}/versions/{base}/diff/{target}`` — server-side version diff (AC-41 / T063).

One endpoint, session-authenticated, shared by the platform's version tab and
the client's review view (design D15: "one component, one data source"). The
diff is computed here from the two frozen snapshots; **neither archive is ever
sent to the browser**, and the patch text is bounded (see
``version_diff_service``'s module docstring for the three caps).

``base`` is the older side (``a/``), ``target`` the newer (``b/``); AC-41's
"the iteration against the last published version" is therefore
``/versions/{current_version_id}/diff/{pending_version_id}``. Refusals ride
in the 200 envelope for the same reason every read of this face does (K11 ②).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from bisheng.app_publish.domain.services.version_diff_service import VersionDiffService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/apps", tags=["HostedAppReview"])


@router.get(
    "/{app_id}/versions/{base_version_id}/diff/{target_version_id}",
    response_model=UnifiedResponseModel[dict],
    summary="What changed between two versions of a hosted application (computed server-side)",
)
async def get_version_diff(
    app_id: str,
    base_version_id: str,
    target_version_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Design §4.2 ⑨ — ``{base, target, role, summary, files[{path,change,additions,deletions,comparable,reason}], patches[{path,change,patch,truncated,masked_secrets}]}``."""
    return resp_200(
        data=await VersionDiffService.diff(app_id, base_version_id, target_version_id, actor=user),
    )
