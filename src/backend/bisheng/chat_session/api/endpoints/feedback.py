from fastapi import APIRouter, Body, Depends

from bisheng.api.v1.schemas import resp_200
from bisheng.chat_session.domain.schemas.feedback import CommentMessageInput, LikeMessageInput
from bisheng.chat_session.domain.services.chat_feedback_service import ChatFeedbackService
from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService
from bisheng.common.dependencies.user_deps import UserPayload

router = APIRouter()


@router.post("/liked", status_code=200)
async def like_response(*, data: LikeMessageInput, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await ChatFeedbackService.update(data.message_id, login_user, liked=data.liked))


@router.post("/chat/copied", status_code=200)
def copied_message(message_id: int = Body(embed=True)):
    """Upload copied message data."""
    ChatMessageService.mark_copied(message_id)
    return resp_200()


@router.post("/chat/comment", status_code=200)
async def comment_resp(*, data: CommentMessageInput, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await ChatFeedbackService.update(data.message_id, login_user, comment=data.comment))
