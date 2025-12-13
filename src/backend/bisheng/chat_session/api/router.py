from typing import Optional, Literal

from fastapi import APIRouter, Depends, Body

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.schemas.api import resp_200
from bisheng.common.schemas.telemetry.event_data_schema import MessageFeedbackEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSessionDao
from ..domain.chat import ChatSessionService

router = APIRouter(prefix='/session', tags=['Chat Session'])


@router.get('/chat/history')
async def get_chat_message_public(*,
                                  chat_id: str,
                                  flow_id: str,
                                  id: Optional[str] = None,
                                  page_size: Optional[int] = 20,
                                  login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ api for audit module and mark qa """
    history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)
    return resp_200(data=history)


@router.post('/chat/message/telemetry')
async def post_chat_message_telemetry(*,
                                      message_id: int = Body(...),
                                      operation_type: Literal['like', 'dislike', 'copy'] = Body(...),
                                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ api for telemetry user feedback """
    message_info = await ChatMessageDao.aget_message_by_id(message_id)
    if not message_info:
        raise NotFoundError()
    chat_info = await MessageSessionDao.async_get_one(message_info.chat_id)
    if not chat_info:
        raise NotFoundError()
    await telemetry_service.log_event(user_id=login_user.user_id,
                                      event_type=BaseTelemetryTypeEnum.MESSAGE_FEEDBACK,
                                      trace_id=trace_id_var.get(),
                                      event_data=MessageFeedbackEventData(
                                          message_id=message_id,
                                          app_id=chat_info.flow_id,
                                          app_name=chat_info.flow_name,
                                          app_type=ApplicationTypeEnum.SKILL,
                                          operation_type=operation_type,
                                      ))
    return resp_200()
