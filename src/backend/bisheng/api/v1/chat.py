import json
from typing import Optional, Union

from fastapi import APIRouter, Body, Query, Request
from fastapi.params import Depends
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.api.v1.schema.chat_schema import AppChatList
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import AddChatMessages, ChatInput, ChatList, resp_200
from bisheng.chat.manager import ChatManager
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError, ServerError
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData, DeleteMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.logger import trace_id_var
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowStatus, FlowType
from bisheng.database.models.mark_record import MarkRecordDao, MarkRecordStatus
from bisheng.database.models.mark_task import MarkTaskDao
from bisheng.database.models.message import ChatMessage, ChatMessageDao, LikedType
from bisheng.database.models.session import MessageSession, MessageSessionDao, SensitiveStatus
from bisheng.database.models.user_group import UserGroupDao
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import get_request_ip

router = APIRouter(tags=['Chat'])
chat_manager = ChatManager()


def get_session_app_type(flow_type: int) -> ApplicationTypeEnum:
    if flow_type == FlowType.WORKFLOW.value:
        return ApplicationTypeEnum.WORKFLOW
    if flow_type == FlowType.ASSISTANT.value:
        return ApplicationTypeEnum.ASSISTANT
    if flow_type == FlowType.LINSIGHT.value:
        return ApplicationTypeEnum.LINSIGHT
    return ApplicationTypeEnum.DAILY_CHAT


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
    """ By annotating tasksIDGet the corresponding session list """

    group_flow_ids = []
    flow_ids, user_ids = [], []

    user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
    if task_id:
        if not login_user.is_admin():
            task = MarkTaskDao.get_task_byid(task_id)
            if str(login_user.user_id) not in task.process_users.split(','):
                raise UnAuthorizedError()
            # Determine if it is a user group administrator
            if user_groups:
                task = MarkTaskDao.get_task_byid(task_id)
                group_flow_ids = task.app_id.split(',')
                # group_flow_ids.extend([app_id for one in t_list for app_id in one.app_id.split(",")])
                if not group_flow_ids:
                    return resp_200(PageList(list=[], total=0))
            else:
                task = MarkTaskDao.get_task_byid(task_id)
                if str(login_user.user_id) not in task.process_users.split(','):
                    raise UnAuthorizedError()
                # Normal
                # user_ids = [login_user.user_id]
                group_flow_ids = MarkTaskDao.get_task_byid(task_id).app_id.split(',')

        else:
            group_flow_ids = MarkTaskDao.get_task_byid(task_id).app_id.split(',')

    if keyword:
        flows = FlowDao.get_flow_list_by_name(name=keyword)
        assistants, _ = AssistantDao.get_all_assistants(name=keyword, page=0, limit=0)
        users = UserDao.search_user_by_name(user_name=keyword)
        if flows:
            flow_ids = [flow.id for flow in flows]
        if assistants:
            flow_ids.extend([assistant.id for assistant in assistants])
        if user_ids:
            user_ids = [user.user_id for user in users]
        # Retrieval content is empty
        if not flow_ids and not user_ids:
            return resp_200(PageList(list=[], total=0))

    if group_flow_ids:
        if flow_ids and keyword:
            flow_ids = flow_ids
        else:
            flow_ids = group_flow_ids

    # Get session list
    res = MessageSessionDao.filter_session(flow_ids=flow_ids, user_ids=user_ids)
    total = len(res)

    # Query the status of a session
    chat_status_ids = [one.chat_id for one in res]
    chat_status_ids = MarkRecordDao.filter_records(task_id=task_id, chat_ids=chat_status_ids)
    chat_status_ids = {one.session_id: one for one in chat_status_ids}

    result = []
    for one in res:
        tmp = AppChatList(
            chat_id=one.chat_id,
            flow_id=one.flow_id,
            flow_name=one.flow_name,
            flow_type=one.flow_type,
            user_id=one.user_id,
            user_name=str(one.user_id),
            create_time=one.create_time,
            like_count=one.like,
            dislike_count=one.dislike,
            copied_count=one.copied,
            mark_status=MarkRecordStatus.DEFAULT.value,
            mark_user=None,
        )
        if mark_info := chat_status_ids.get(one.chat_id):
            tmp.mark_id = mark_info.create_id
            tmp.mark_status = mark_info.status if mark_info.status is not None else 1
            tmp.mark_user = mark_info.create_user
        if mark_status:
            if mark_status != tmp.mark_status:
                continue
        if mark_user:
            users = [int(one) for one in mark_user.split(',')]
            if tmp.mark_id not in users:
                continue
        result.append(tmp)

    result = result[(page_num - 1) * page_size: page_num * page_size]

    return resp_200(PageList(list=result, total=total))


@router.get('/chat/history')
async def get_chat_message(*,
                           chat_id: str,
                           flow_id: str,
                           id: Optional[str] = None,
                           page_size: Optional[int] = 20,
                           login_user: UserPayload = Depends(UserPayload.get_login_user),
                           share_link: Union['ShareLink', None] = Depends(header_share_token_parser)):
    history = await ChatSessionService.get_chat_history(chat_id, flow_id, id, page_size)

    # # Authorization check
    if history and login_user.user_id != history[0].user_id:
        if not share_link or share_link.resource_id != chat_id:
            return UnAuthorizedError.return_resp()
    return resp_200(history)


@router.get('/chat/info')
async def get_chat_info(chat_id: str = Query(..., description='Session Uniqueid，chai_id')):
    """ Setujuchat_idGet session details """
    res = await MessageSessionDao.async_get_one(chat_id)
    res.flow_logo = WorkFlowService.get_logo_share_link(res.flow_logo)
    return resp_200(res)


@router.post('/chat/conversation/rename')
async def rename(conversationId: str = Body(..., description='Sessionsid', embed=True),
                 name: str = Body(..., description='Session name', embed=True),
                 login_user: UserPayload = Depends(UserPayload.get_login_user)):
    await MessageSessionDao.update_session_name(conversationId, name)
    return resp_200()


@router.delete('/chat/{chat_id}', status_code=200)
async def del_chat_id(*,
                      request: Request,
                      chat_id: str,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # Get a message
    session_chat = await MessageSessionDao.async_get_one(chat_id)

    if not session_chat or session_chat.is_delete:
        return resp_200()
    if session_chat.flow_type == FlowType.ASSISTANT.value:
        assistant_info = await AssistantDao.aget_one_assistant(session_chat.flow_id)
        if assistant_info:
            await AuditLogService.delete_chat_assistant(login_user, get_request_ip(request), assistant_info)
    elif session_chat.flow_type == FlowType.WORKSTATION.value:
        await AuditLogService.delete_chat_message(login_user, get_request_ip(request), session_chat)
    else:
        flow_info = await FlowDao.aget_flow_by_id(session_chat.flow_id)
        if flow_info and flow_info.flow_type == FlowType.WORKFLOW.value:
            await AuditLogService.delete_chat_workflow(login_user, get_request_ip(request), flow_info)

    # Set the delete state of the session
    await MessageSessionDao.delete_session(chat_id)

    # RecordTelemetryJournal
    await telemetry_service.log_event(user_id=login_user.user_id,
                                      event_type=BaseTelemetryTypeEnum.DELETE_MESSAGE_SESSION,
                                      trace_id=trace_id_var.get(),
                                      event_data=DeleteMessageSessionEventData(session_id=chat_id)
                                      )

    return resp_200()


@router.post('/chat/message', status_code=200)
def add_chat_messages(*,
                      request: Request,
                      data: AddChatMessages,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Add a full Q&A record, Security Check Write Usage
    """
    logger.debug(f'gateway add_chat_messages {data}')
    flow_id = data.flow_id
    chat_id = data.chat_id
    if not chat_id or not flow_id:
        raise ServerError.http_exception()
    save_human_message = data.human_message
    flow_info = FlowDao.get_flow_by_id(flow_id)
    if flow_info and flow_info.flow_type == FlowType.WORKFLOW.value:
        # The input of the workflow, the actual input needs to be parsed from the input
        try:
            tmp_human_message = json.loads(data.human_message)
            for node_id, node_input in tmp_human_message.items():
                save_human_message = node_input.get('message')
        except:
            save_human_message = data.human_message

    human_message = ChatMessage(flow_id=flow_id,
                                chat_id=chat_id,
                                user_id=login_user.user_id,
                                is_bot=False,
                                message=save_human_message,
                                sensitive_status=SensitiveStatus.VIOLATIONS.value,
                                type='human',
                                category='question')
    bot_message = ChatMessage(flow_id=flow_id,
                              chat_id=chat_id,
                              user_id=login_user.user_id,
                              is_bot=True,
                              message=data.answer_message,
                              sensitive_status=SensitiveStatus.PASS.value,
                              type='bot',
                              category='answer')
    message_dbs = ChatMessageDao.insert_batch([human_message, bot_message])
    # Update session status
    MessageSessionDao.update_sensitive_status(chat_id, SensitiveStatus.VIOLATIONS)

    # Write Audit Log, Determine if it is a new session
    session_info = MessageSessionDao.get_one(chat_id=chat_id)
    if not session_info:
        if flow_info:
            session_info = MessageSessionDao.insert_one(MessageSession(
                chat_id=chat_id,
                flow_id=flow_id,
                flow_type=flow_info.flow_type,
                flow_name=flow_info.name,
                user_id=login_user.user_id,
                sensitive_status=SensitiveStatus.VIOLATIONS.value,
            ))
            if flow_info.flow_type == FlowType.WORKFLOW.value:
                AuditLogService.create_chat_workflow(login_user, get_request_ip(request), flow_id, flow_info)
        else:
            assistant_info = AssistantDao.get_one_assistant(flow_id)
            if assistant_info:
                session_info = MessageSessionDao.insert_one(MessageSession(
                    chat_id=chat_id,
                    flow_id=flow_id,
                    flow_type=FlowType.ASSISTANT.value,
                    flow_name=assistant_info.name,
                    user_id=login_user.user_id,
                    sensitive_status=SensitiveStatus.VIOLATIONS.value,
                ))
                AuditLogService.create_chat_assistant(login_user, get_request_ip(request),
                                                      flow_id)
        if session_info:
            # RecordTelemetryJournal
            telemetry_service.log_event_sync(user_id=login_user.user_id,
                                             event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                                             trace_id=trace_id_var.get(),
                                             event_data=NewMessageSessionEventData(
                                                 session_id=session_info.chat_id,
                                                 app_id=flow_id,
                                                 source="platform",
                                                 app_name=session_info.flow_name,
                                                 app_type=get_session_app_type(session_info.flow_type)
                                             ))

    return resp_200(data=message_dbs)


@router.put('/chat/message/{message_id}', status_code=200)
def update_chat_message(*,
                        message_id: int,
                        message: str = Body(embed=True),
                        category: str = Body(default=None, embed=True),
                        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Update the content of a message Security Check Usage"""
    logger.info(
        f'update_chat_message message_id={message_id} message={message} login_user={login_user.user_name}'
    )
    chat_message = ChatMessageDao.get_message_by_id(message_id)
    if not chat_message:
        return NotFoundError.return_resp()
    if chat_message.user_id != login_user.user_id:
        return UnAuthorizedError.return_resp()

    chat_message.message = message
    if category:
        chat_message.category = category
    chat_message.source = False
    chat_message.sensitive_status = SensitiveStatus.VIOLATIONS.value

    ChatMessageDao.update_message_model(chat_message)

    MessageSessionDao.update_sensitive_status(chat_message.chat_id, SensitiveStatus.VIOLATIONS)

    return resp_200()


@router.delete('/chat/message/{message_id}', status_code=200)
def del_message_id(*, message_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ChatMessageDao.delete_by_message_id(login_user.user_id, message_id)

    return resp_200()


@router.post('/liked', status_code=200)
def like_response(*, data: ChatInput):
    message_id = data.message_id
    message = ChatMessageDao.get_message_by_id(data.message_id)
    if not message:
        raise NotFoundError.http_exception()

    if message.liked == data.liked:
        return resp_200()

    like_count = 0
    dislike_count = 0
    if message.liked == LikedType.UNRATED.value:
        if data.liked == LikedType.LIKED.value:
            like_count = 1
        elif data.liked == LikedType.DISLIKED.value:
            dislike_count = 1
    elif message.liked == LikedType.LIKED.value:
        like_count = -1
        if data.liked == LikedType.DISLIKED.value:
            dislike_count = 1
    elif message.liked == LikedType.DISLIKED.value:
        dislike_count = -1
        if data.liked == LikedType.LIKED.value:
            like_count = 1

    message.liked = data.liked
    ChatMessageDao.update_message_model(message)
    logger.info('k=s act=liked message_id={} liked={}', message_id, data.liked)

    # Number of thumbs up and down steps in the update session table
    MessageSessionDao.add_like_count(message.chat_id, like_count)
    MessageSessionDao.add_dislike_count(message.chat_id, dislike_count)

    return resp_200()


@router.post('/chat/copied', status_code=200)
def copied_message(message_id: int = Body(embed=True)):
    """ Upload CopymessageData """
    message = ChatMessageDao.get_message_by_id(message_id)
    if not message:
        raise NotFoundError.http_exception()
    if message.copied != 1:
        ChatMessageDao.update_message_copied(message_id, 1)
        MessageSessionDao.add_copied_count(message.chat_id, 1)
    return resp_200()


@router.post('/chat/comment', status_code=200)
def comment_resp(*, data: ChatInput):
    comment_answer(data.message_id, data.comment)
    return resp_200()


@router.get('/chat/list')
def get_session_list(page: Optional[int] = Query(default=1, ge=1, le=1000),
                     limit: Optional[int] = Query(default=10, ge=1, le=100),
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get session list sorted by update_time descending.
    Only shows daily chat (WORKSTATION) and linsight sessions.
    """
    # Define allowed flow types: WORKSTATION(15) and LINSIGHT(20)
    allowed_flow_types = [FlowType.WORKSTATION.value, FlowType.LINSIGHT.value]

    # Query sessions with allowed flow types, sorted by update_time descending
    res = MessageSessionDao.filter_session(
        user_ids=[login_user.user_id],
        flow_type=allowed_flow_types,
        page=page,
        limit=limit,
        include_delete=False,
        order_by_update_time=True
    )

    if not res:
        return resp_200([])

    # Get related data
    chat_ids = [one.chat_id for one in res]

    latest_messages = ChatMessageDao.get_latest_message_by_chat_ids(
        chat_ids,
        exclude_category=WorkflowEventType.UserInput.value
    )
    latest_messages = {one.chat_id: one for one in latest_messages}

    # Build ChatList objects (already sorted by update_time descending from query)
    chat_sessions = [
        ChatList(
            chat_id=one.chat_id,
            flow_id=one.flow_id,
            flow_name=one.flow_name,
            flow_type=one.flow_type,
            name=one.name,
            logo=BaseService.get_logo_share_link(one.flow_logo) if one.flow_logo else '',
            latest_message=latest_messages.get(one.chat_id, None),
            create_time=one.create_time,
            update_time=one.update_time
        ) for one in res
    ]

    return resp_200(chat_sessions)


# Access to online workflows and assistants
@router.get('/chat/online')
def get_online_chat(*,
                    keyword: Optional[str] = None,
                    tag_id: Optional[int] = None,
                    page: Optional[int] = 1,
                    limit: Optional[int] = 10,
                    user: UserPayload = Depends(UserPayload.get_login_user)):
    data, _ = WorkFlowService.get_all_flows(user, keyword, FlowStatus.ONLINE.value, tag_id, None, page, limit)
    return resp_200(data=data)
