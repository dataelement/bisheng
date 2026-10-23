"""Stable addresses for parsed images in workflow conversation Markdown."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.dependencies.user_deps import UserPayload

router = APIRouter()


@router.get("/chat/{chat_id}/files/{file_id}/content")
async def get_chat_attachment_content(
    chat_id: str,
    file_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Every image request checks ownership before issuing a fresh signed redirect."""
    url = await ChatSessionService.resolve_attachment_url(chat_id, file_id, login_user)
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})
