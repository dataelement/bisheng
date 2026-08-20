from typing import Union

from fastapi import APIRouter, Body, Query, Request
from fastapi.params import Depends

from bisheng.api.v1.schemas import AddChatMessages, resp_200
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.services.chat_message_service import ChatMessageService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import bypass_tenant_filter_if
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import get_request_ip

router = APIRouter()


@router.get("/chat/app/list")
def get_app_chat_list(
    *,
    keyword: str | None = None,
    mark_user: str | None = None,
    mark_status: int | None = None,
    task_id: int | None = Query(default=None, description="Callout TaskID"),
    flow_type: int | None = None,
    page_num: int | None = 1,
    page_size: int | None = 20,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
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


@router.get("/chat/history")
async def get_chat_message(
    *,
    chat_id: str,
    flow_id: str,
    id: str | None = None,
    page_size: int | None = 20,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    share_link: Union["ShareLink", None] = Depends(header_share_token_parser),
):
    with bypass_tenant_filter_if(share_link is not None):
        history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)

    if history and login_user.user_id != history[0].user_id:
        if not share_link or share_link.resource_id != chat_id:
            return UnAuthorizedError.return_resp()
    return resp_200(history)


@router.get("/chat/info")
async def get_chat_info(
    chat_id: str = Query(..., description="Session Uniqueid，chat_id"),
    share_link: Union["ShareLink", None] = Depends(header_share_token_parser),
):
    """Get session details by chat_id.

    ``message_session`` is tenant-aware, so a share recipient in another child
    tenant would read None and see the fallback "New Chat" title instead of the
    conversation's real name.
    """
    with bypass_tenant_filter_if(share_link is not None):
        res = await ChatSessionService.get_session_info(chat_id)
    return resp_200(res)


@router.post("/chat/conversation/rename")
async def rename(
    conversationId: str = Body(..., description="Session sid", embed=True),
    name: str = Body(..., description="Session name", embed=True),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    await ChatSessionService.rename_session(conversationId, name)
    return resp_200()


@router.delete("/chat/{chat_id}", status_code=200)
async def del_chat_id(*, request: Request, chat_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    await ChatSessionService.delete_session(chat_id, login_user, get_request_ip(request))
    return resp_200()


@router.get("/chat/{chat_id}/files/{file_id}/url", status_code=200)
async def get_chat_attachment_url(
    *, request: Request, chat_id: str, file_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """Fresh link for an attachment of this conversation.

    The link issued at upload time expires; the client asks for a new one when
    it renders. Which object gets signed is decided from the conversation's own
    messages, never from anything the caller sends.
    """
    url = await ChatSessionService.resolve_attachment_url(chat_id, file_id, login_user)
    return resp_200(data={"url": url})


@router.post("/chat/message", status_code=200)
def add_chat_messages(
    *, request: Request, data: AddChatMessages, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """Add a full Q&A record. Security check write usage."""
    message_dbs = ChatMessageService.add_qa_messages(data, login_user, get_request_ip(request))
    return resp_200(data=message_dbs)


@router.put("/chat/message/{message_id}", status_code=200)
def update_chat_message(
    *,
    message_id: int,
    message: str = Body(embed=True),
    category: str = Body(default=None, embed=True),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Update the content of a message. Security check usage."""
    ChatMessageService.update_message(message_id, message, category, login_user)
    return resp_200()


@router.delete("/chat/message/{message_id}", status_code=200)
def del_message_id(*, message_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ChatMessageService.delete_message(login_user.user_id, message_id)
    return resp_200()


@router.get("/chat/list")
def get_session_list(
    page: int | None = Query(default=1, ge=1, le=1000),
    limit: int | None = Query(default=10, ge=1, le=100),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Get session list sorted by update_time descending. Only shows daily chat and linsight sessions."""
    chat_sessions = ChatSessionService.get_user_session_list(login_user.user_id, page, limit)
    return resp_200(chat_sessions)
