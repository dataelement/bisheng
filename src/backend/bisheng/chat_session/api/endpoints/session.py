from typing import Literal

from fastapi import APIRouter, Body, Depends

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.workstation import WorkstationMessage
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.utils import get_session_app_type
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.schemas.api import resp_200
from bisheng.common.schemas.telemetry.event_data_schema import MessageFeedbackEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao

router = APIRouter()


@router.get("/chat/history")
async def get_chat_message_public(
    *,
    chat_id: str,
    flow_id: str,
    id: str | None = None,
    page_size: int | None = 20,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """API for audit module and mark QA."""
    session_info = await MessageSessionDao.async_get_one(chat_id)
    if session_info is not None:
        try:
            await AuditLogService.assert_session_in_audit_scope(
                login_user, chat_id, session_owner_id=session_info.user_id, app_id=session_info.flow_id
            )
        except UnAuthorizedError:
            raise UnAuthorizedError.http_exception()
    history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)
    return resp_200(data=history)


@router.get("/chat/messages/{conversationId}")
async def get_chat_messages_by_conversation_id(
    *, conversationId: str, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """API for getting chat messages by conversation id (audit detail; F003 scope-checked)."""
    try:
        await AuditLogService.assert_session_in_audit_scope(login_user, conversationId)
    except UnAuthorizedError:
        raise UnAuthorizedError.http_exception()
    messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversationId, limit=1000)
    if not messages:
        raise NotFoundError()

    return resp_200([await WorkstationMessage.from_chat_message(message) for message in messages])


@router.get("/chat/{chat_id}/files/{file_id}/url")
async def get_chat_generated_file_url(
    *, chat_id: str, file_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """Fresh link to a code-interpreter file of a conversation (audit detail; F016)."""
    try:
        await AuditLogService.assert_session_in_audit_scope(login_user, chat_id)
    except UnAuthorizedError:
        raise UnAuthorizedError.http_exception()
    url = await ChatSessionService.resolve_audit_attachment_url(chat_id, file_id)
    return resp_200(data={"url": url})


@router.post("/chat/message/telemetry")
async def post_chat_message_telemetry(
    *,
    message_id: int = Body(...),
    operation_type: Literal["like", "dislike", "copy"] = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """API for telemetry user feedback."""
    message_info = await ChatMessageDao.aget_message_by_id(message_id)
    if not message_info:
        raise NotFoundError()
    chat_info = await MessageSessionDao.async_get_one(message_info.chat_id)
    if not chat_info:
        raise NotFoundError()
    await telemetry_service.log_event(
        user_id=login_user.user_id,
        event_type=BaseTelemetryTypeEnum.MESSAGE_FEEDBACK,
        trace_id=trace_id_var.get(),
        event_data=MessageFeedbackEventData(
            message_id=message_id,
            app_id=chat_info.flow_id,
            app_name=chat_info.flow_name,
            app_type=get_session_app_type(chat_info.flow_type),
            operation_type=operation_type,
        ),
    )
    return resp_200()
