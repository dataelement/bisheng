"""Publication-bound history and title adapters."""

from __future__ import annotations

from fastapi import APIRouter, Body, Query

from bisheng.api.v1.schemas import resp_200
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.public_endpoints.domain.services.guest_policy import public_application_execution

router = APIRouter(prefix="/chat", tags=["PublicAPI", "Chat"])


@router.get("/history")
async def get_chat_history(
    chat_id: str = Query(...),
    flow_id: str = Query(...),
    id: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=1000),
):
    async with public_application_execution(flow_id) as execution:
        await ChatSessionService.get_subject_session(chat_id, execution.session_subject)
        history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)
        return resp_200(data=history)


@router.post("/gen_title")
async def generate_title(conversationId: str = Body(..., embed=True)):
    unresolved = await ChatSessionService.get_public_session_for_resolution(conversationId)
    async with public_application_execution(unresolved.flow_id) as execution:
        title = await ChatSessionService.wait_for_subject_title(
            conversationId,
            execution.session_subject,
        )
        return resp_200(data={"title": title})
