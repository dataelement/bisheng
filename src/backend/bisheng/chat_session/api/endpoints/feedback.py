from fastapi import APIRouter, Body, Depends

from bisheng.api.v1.schemas import ChatInput, resp_200
from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService
from bisheng.common.dependencies.user_deps import UserPayload

router = APIRouter()


@router.post("/liked", status_code=200)
def like_response(*, data: ChatInput, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ChatMessageService.like_response(data, login_user)
    return resp_200()


@router.post("/chat/copied", status_code=200)
def copied_message(message_id: int = Body(embed=True), login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Upload copied message data."""
    ChatMessageService.mark_copied(message_id, login_user)
    return resp_200()


@router.post("/chat/comment", status_code=200)
def comment_resp(*, data: ChatInput, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ChatMessageService.comment_on_answer(data.message_id, data.comment, login_user)
    return resp_200()
