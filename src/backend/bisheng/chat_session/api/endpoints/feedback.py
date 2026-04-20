from fastapi import APIRouter, Body

from bisheng.api.v1.schemas import ChatInput, resp_200
from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService

router = APIRouter()


@router.post('/liked', status_code=200)
def like_response(*, data: ChatInput):
    ChatMessageService.like_response(data)
    return resp_200()


@router.post('/chat/copied', status_code=200)
def copied_message(message_id: int = Body(embed=True)):
    """Upload copied message data."""
    ChatMessageService.mark_copied(message_id)
    return resp_200()


@router.post('/chat/comment', status_code=200)
def comment_resp(*, data: ChatInput):
    ChatMessageService.comment_on_answer(data.message_id, data.comment)
    return resp_200()
