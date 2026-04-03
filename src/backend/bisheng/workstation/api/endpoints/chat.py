import asyncio
from typing import Union

from fastapi import APIRouter, Body, Request

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.api.v1.schemas import resp_200
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.workstation.domain.schemas import WorkstationMessage

from ..dependencies import LoginUserDep, ShareLink, ShareLinkDep
from ...domain.services.chat_service import stream_chat_completion

router = APIRouter()


@router.post('/gen_title')
async def gen_title(conversationId: str = Body(..., embed=True), login_user=LoginUserDep):
    await asyncio.sleep(5)
    messages = await MessageSessionDao.async_get_one(conversationId)
    return resp_200(data={'title': messages.name if messages else 'New Chat'})


@router.get('/messages/{conversationId}')
async def get_chat_history(
    conversationId: str,
    login_user=LoginUserDep,
    share_link: Union[ShareLink, None] = ShareLinkDep,
):
    messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversationId, limit=1000)
    if not messages:
        return resp_200([])
    if login_user.user_id != messages[0].user_id:
        if not share_link or share_link.resource_id != conversationId:
            return UnAuthorizedError.return_resp()
    citation_map = await ChatSessionService.get_message_citations_by_message_ids(
        [message.id for message in messages if message.id is not None],
    )
    return resp_200([
        await WorkstationMessage.from_chat_message(
            message,
            citations=citation_map.get(message.id) if message.id is not None else None,
        )
        for message in messages
    ])


@router.post('/chat/completions')
async def chat_completions(
    request: Request,
    data: APIChatCompletion,
    login_user=LoginUserDep,
):
    return await stream_chat_completion(request, data, login_user)
