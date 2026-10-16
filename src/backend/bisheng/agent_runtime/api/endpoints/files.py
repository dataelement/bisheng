"""Download endpoint for agent deliverable files (F078 design decision 7)."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from bisheng.agent_runtime.domain.services.file_access import aresolve_deliverable_url
from bisheng.common.dependencies.user_deps import UserPayload

router = APIRouter(prefix="/files", tags=["AgentRuntime"])


@router.get("/{session_key}/{file_id}", summary="Download a deliverable file of an agent run")
async def download_deliverable(
    session_key: str,
    file_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> RedirectResponse:
    # Authorize first, then redirect to a short-lived signed link.
    url = await aresolve_deliverable_url(session_key, file_id, login_user)
    return RedirectResponse(url=url, status_code=302)
