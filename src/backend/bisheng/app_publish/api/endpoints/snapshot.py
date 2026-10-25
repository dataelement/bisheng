"""``/api/v1/apps/{app_id}/versions/{version_id}/snapshot/*`` — the review view's read-only source browsing (AC-25 / T052).

Session-authenticated, consumed by the client's review view (approvers) and
usable from the platform's version tab (owners). Two reads, nothing else:

* ``…/snapshot/tree`` — the file tree, flat and sorted, with a per-file
  ``previewable`` verdict so the client can grey out what the next call would
  refuse to show.
* ``…/snapshot/file?path=…`` — one file's text, secrets masked; binary and
  over-sized files come back as ``previewable: false`` with the reason, not
  as bytes.
* ``…/review-context`` — the version history and the id of the currently
  published version, so the review view can fill its 版本历史 tab and know
  what to diff the pending version against. Its own read because neither
  ``publish-status`` nor F054's version list admits an approver.

Every refusal — not owner / not approver, no such version, snapshot swept,
file missing — rides in the 200 envelope as a business code (16257 / 16253 /
16256 / 16258). The platform SPA's interceptor navigates the whole page to
``/403`` on a real 403 or 404 (design K11 ②), and the client's review view is
a panel inside the settings page that must keep rendering.

There is deliberately **no download endpoint**: the design sentence for this
wave is "the source never reaches the browser as an archive" (D15). What can
be read is one file at a time, masked, under the scanner's own ceiling.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from bisheng.app_publish.domain.services.snapshot_browse_service import SnapshotBrowseService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/apps", tags=["HostedAppReview"])


@router.get(
    "/{app_id}/versions/{version_id}/snapshot/tree",
    response_model=UnifiedResponseModel[dict],
    summary="File tree of one version's frozen package (read-only)",
)
async def get_snapshot_tree(
    app_id: str,
    version_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Design §4.2 ⑨ — ``{version, role, entries[{path,name,type,size,previewable,reason}], total_files, truncated}``."""
    return resp_200(data=await SnapshotBrowseService.list_tree(app_id, version_id, actor=user))


@router.get(
    "/{app_id}/versions/{version_id}/snapshot/file",
    response_model=UnifiedResponseModel[dict],
    summary="One file of one version's frozen package (read-only, secrets masked)",
)
async def get_snapshot_file(
    app_id: str,
    version_id: str,
    path: str = Query(..., min_length=1, max_length=1024, description="Package-relative POSIX path"),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Design §4.2 ⑨ — ``{version, role, path, size, previewable, reason, content, masked_secrets, line_count}``."""
    return resp_200(data=await SnapshotBrowseService.read_file(app_id, version_id, path, actor=user))


@router.get(
    "/{app_id}/versions/{version_id}/review-context",
    response_model=UnifiedResponseModel[dict],
    summary="Version history and diff sides for the review view (read-only)",
)
async def get_review_context(
    app_id: str,
    version_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Design §4.2 ⑨ — ``{version, role, current_version_id, pending_version_id, versions[]}``."""
    return resp_200(data=await SnapshotBrowseService.review_context(app_id, version_id, actor=user))
