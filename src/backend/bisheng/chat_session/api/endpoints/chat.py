import asyncio
from typing import Optional, Union

from fastapi import APIRouter, Body, Query, Request
from fastapi.params import Depends
from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.api.v1.schemas import AddChatMessages, ChatList, resp_200
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.database.models.session import MessageSessionDao
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import get_request_ip

router = APIRouter()


@router.get('/chat/app/list')
def get_app_chat_list(*,
                      keyword: Optional[str] = None,
                      mark_user: Optional[str] = None,
                      mark_status: Optional[int] = None,
                      task_id: Optional[int] = Query(default=None, description='Callout TaskID'),
                      flow_type: Optional[int] = None,
                      page_num: Optional[int] = 1,
                      page_size: Optional[int] = 20,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Get session list filtered by annotation task."""
    result = ChatSessionService.get_app_chat_list(
        login_user=login_user,
        keyword=keyword,
        mark_user=mark_user,
        mark_status=mark_status,
        task_id=task_id,
        flow_type=flow_type,
        page_num=page_num,
        page_size=page_size,
    )
    return resp_200(result)


@router.get('/chat/history')
async def get_chat_message(*,
                           chat_id: str,
                           flow_id: str,
                           id: Optional[str] = None,
                           page_size: Optional[int] = 20,
                           login_user: UserPayload = Depends(UserPayload.get_login_user),
                           share_link: Union['ShareLink', None] = Depends(header_share_token_parser)):
    history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)

    if history and login_user.user_id != history[0].user_id:
        if not share_link or share_link.resource_id != chat_id:
            return UnAuthorizedError.return_resp()
    return resp_200(history)


@router.get('/chat/info')
async def get_chat_info(chat_id: str = Query(..., description='Session Uniqueid，chat_id')):
    """Get session details by chat_id."""
    res = await ChatSessionService.get_session_info(chat_id)
    return resp_200(res)


@router.post('/chat/conversation/rename')
async def rename(conversationId: str = Body(..., description='Session sid', embed=True),
                 name: str = Body(..., description='Session name', embed=True),
                 login_user: UserPayload = Depends(UserPayload.get_login_user)):
    await ChatSessionService.rename_session(conversationId, name)
    return resp_200()


@router.delete('/chat/{chat_id}', status_code=200)
async def del_chat_id(*,
                      request: Request,
                      chat_id: str,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    await ChatSessionService.delete_session(chat_id, login_user, get_request_ip(request))
    return resp_200()


@router.post('/chat/message', status_code=200)
def add_chat_messages(*,
                      request: Request,
                      data: AddChatMessages,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Add a full Q&A record. Security check write usage."""
    message_dbs = ChatMessageService.add_qa_messages(data, login_user, get_request_ip(request))
    return resp_200(data=message_dbs)


@router.put('/chat/message/{message_id}', status_code=200)
def update_chat_message(*,
                        message_id: int,
                        message: str = Body(embed=True),
                        category: str = Body(default=None, embed=True),
                        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Update the content of a message. Security check usage."""
    ChatMessageService.update_message(message_id, message, category, login_user)
    return resp_200()


@router.delete('/chat/message/{message_id}', status_code=200)
def del_message_id(*, message_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ChatMessageService.delete_message(login_user.user_id, message_id)
    return resp_200()


@router.get('/chat/list')
def get_session_list(page: Optional[int] = Query(default=1, ge=1, le=1000),
                     limit: Optional[int] = Query(default=10, ge=1, le=100),
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Get session list sorted by update_time descending. Only shows daily chat and linsight sessions."""
    chat_sessions = ChatSessionService.get_user_session_list(login_user.user_id, page, limit)
    return resp_200(chat_sessions)
