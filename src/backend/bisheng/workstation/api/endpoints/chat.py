import asyncio
from typing import Union

from fastapi import APIRouter, Body, Request

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.api.v1.schemas import resp_200
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.workstation.domain.schemas import WorkstationMessage
from bisheng.workstation.domain.services.chat_helpers import (
    _drop_legacy_sibling_branches,
    _is_new_format,
    _format_new_message,
    _convert_legacy_message,
)
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
    return resp_200([
        await WorkstationMessage.from_chat_message(
            message
        )
        for message in messages
    ])


@router.get('/messages/{conversationId}/agent')
async def get_agent_chat_history(
        conversationId: str,
        login_user=LoginUserDep,
        share_link: Union[ShareLink, None] = ShareLinkDep,
):
    """v2.5: return chat history in the new ChatResponse (Agent-mode) shape.

    - Legacy regenerate sibling branches are collapsed: only the latest
      `create_time` answer per `parentMessageId` survives (R10 / A2).
    - Legacy plain-text answers are converted on-the-fly to JSON shape
      (thinking / web tool_calls extracted from `:::` markers).
    - New Agent-mode messages pass through.
    """
    messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversationId, limit=1000)
    if not messages:
        return resp_200([])
    if login_user.user_id != messages[0].user_id:
        if not share_link or share_link.resource_id != conversationId:
            return UnAuthorizedError.return_resp()

    # 1. Drop legacy sibling branches (keep only latest per parentMessageId)
    messages = _drop_legacy_sibling_branches(messages)

    # 2. Map each row through the appropriate formatter
    result = []
    for msg in messages:
        if _is_new_format(msg):
            result.append(_format_new_message(msg))
        else:
            result.append(_convert_legacy_message(msg))
    return resp_200(result)


@router.post('/chat/completions')
async def chat_completions(
        request: Request,
        data: APIChatCompletion,
        login_user=LoginUserDep,
):
    return await stream_chat_completion(request, data, login_user)
