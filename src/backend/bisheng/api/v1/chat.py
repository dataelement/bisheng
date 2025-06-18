import json
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import (APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketException,
                     status)
from fastapi.params import Depends
from fastapi.responses import StreamingResponse
from fastapi_jwt_auth import AuthJWT
from sqlmodel import select

from bisheng.api.errcode.base import NotFoundError
from bisheng.api.services import chat_imp
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.base import BaseService
from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.services.knowledge_imp import delete_es, delete_vector
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.utils import build_flow, build_input_keys_response, get_request_ip
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.api.v1.schema.chat_schema import APIChatCompletion, AppChatList
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import (AddChatMessages, BuildStatus, BuiltResponse, ChatInput,
                                    ChatList, InitResponse, StreamData,
                                    UnifiedResponseModel, resp_200)
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.database.base import session_getter
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.mark_record import MarkRecordDao, MarkRecordStatus
from bisheng.database.models.mark_task import MarkTaskDao
from bisheng.database.models.message import ChatMessage, ChatMessageDao, ChatMessageRead, LikedType
from bisheng.database.models.session import MessageSession, MessageSessionDao, SensitiveStatus
from bisheng.database.models.message import ChatMessage, ChatMessageDao, ChatMessageRead, MessageDao, LikedType
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.graph.graph.base import Graph
from bisheng.utils import generate_uuid
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key

router = APIRouter(tags=['Chat'])
chat_manager = ChatManager()
flow_data_store = redis_client
expire = 600  # reids 60s 过期


@router.post('/chat/completions', response_class=StreamingResponse)
async def chat_completions(request: APIChatCompletion, Authorize: AuthJWT = Depends()):
    # messages 为openai 格式。目前不支持openai的复杂多轮，先临时处理
    message = None
    if request.messages:
        last_message = request.messages[-1]
        if 'content' in last_message:
            message = last_message['content']
        else:
            logger.info('last_message={}', last_message)
            message = last_message
    session_id = request.session_id or generate_uuid()

    payload = {'user_name': 'root', 'user_id': 1, 'role': 'admin'}
    access_token = Authorize.create_access_token(subject=json.dumps(payload), expires_time=864000)
    url = f'ws://127.0.0.1:7860/api/v1/chat/{request.model}?chat_id={session_id}&t={access_token}'
    web_conn = await chat_imp.get_connection(url, session_id)

    return StreamingResponse(chat_imp.event_stream(web_conn, message, session_id, request.model,
                                                   request.streaming),
                             media_type='text/event-stream')


@router.get('/chat/app/list')
def get_app_chat_list(*,
                      keyword: Optional[str] = None,
                      mark_user: Optional[str] = None,
                      mark_status: Optional[int] = None,
                      task_id: Optional[int] = Query(default=None, description='标注任务ID'),
                      flow_type: Optional[int] = None,
                      page_num: Optional[int] = 1,
                      page_size: Optional[int] = 20,
                      login_user: UserPayload = Depends(get_login_user)):
    """ 通过标注任务ID获取对应的会话列表 """

    group_flow_ids = []
    flow_ids, user_ids = [], []

    user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
    if task_id:
        if not login_user.is_admin():
            task = MarkTaskDao.get_task_byid(task_id)
            if str(login_user.user_id) not in task.process_users.split(','):
                raise HTTPException(status_code=403, detail='没有权限')
            # 判断下是否是用户组管理员
            if user_groups:
                task = MarkTaskDao.get_task_byid(task_id)
                group_flow_ids = task.app_id.split(',')
                # group_flow_ids.extend([app_id for one in t_list for app_id in one.app_id.split(",")])
                if not group_flow_ids:
                    return resp_200(PageList(list=[], total=0))
            else:
                task = MarkTaskDao.get_task_byid(task_id)
                if str(login_user.user_id) not in task.process_users.split(','):
                    raise HTTPException(status_code=403, detail='没有权限')
                # 普通用户
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
        # 检索内容为空
        if not flow_ids and not user_ids:
            return resp_200(PageList(list=[], total=0))

    if group_flow_ids:
        if flow_ids and keyword:
            flow_ids = flow_ids
        else:
            flow_ids = group_flow_ids

    # 获取会话列表
    flow_ids = [one.replace("-",'') for one in flow_ids]
    res = MessageSessionDao.filter_session(flow_ids=flow_ids, user_ids=user_ids)
    total = len(res)

    # 查询会话的状态
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
            user_name=one.user_id,
            create_time=one.create_time,
            update_time=one.update_time,
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
def get_chatmessage(*,
                    chat_id: str,
                    flow_id: str,
                    id: Optional[str] = None,
                    page_size: Optional[int] = 20,
                    login_user: UserPayload = Depends(get_login_user)):
    if not chat_id or not flow_id:
        return {'code': 500, 'message': 'chat_id 和 flow_id 必传参数'}
    where = select(ChatMessage).where(ChatMessage.flow_id == flow_id,
                                      ChatMessage.chat_id == chat_id)
    if id:
        where = where.where(ChatMessage.id < int(id))
    with session_getter() as session:
        db_message = session.exec(where.order_by(ChatMessage.id.desc()).limit(page_size)).all()
    return resp_200(db_message)


@router.post('/chat/conversation/rename')
def rename(conversationId: str = Body(..., description='会话id', embed=True),
           name: str = Body(..., description='会话名称', embed=True),
           login_user: UserPayload = Depends(get_login_user)):
    conversation = MessageSessionDao.get_one(conversationId)
    conversation.flow_name = name
    MessageSessionDao.insert_one(conversation)
    return resp_200()


@router.post('/chat/conversation/copy')
def copy(conversationId: str = Body(..., description='会话id', embed=True), ):
    conversation = MessageSessionDao.get_one(conversationId)
    conversation.chat_id = uuid4().hex
    conversation = MessageSessionDao.insert_one(conversation)
    msg_list = ChatMessageDao.get_messages_by_chat_id(conversationId)
    if msg_list:
        for msg in msg_list:
            msg.chat_id = conversation.chat_id
            msg.id = None
            ChatMessageDao.insert_one(msg)


@router.get('/chat/history',
            response_model=UnifiedResponseModel[List[ChatMessageRead]],
            status_code=200)
def get_chatmessage(*,
                    chat_id: str,
                    flow_id: str,
                    id: Optional[str] = None,
                    page_size: Optional[int] = 20,
                    login_user: UserPayload = Depends(get_login_user)):
    if not chat_id or not flow_id:
        return {'code': 500, 'message': 'chat_id 和 flow_id 必传参数'}
    flow_id = flow_id.replace("-",'')
    where = select(ChatMessage).where(ChatMessage.flow_id == flow_id,
                                      ChatMessage.chat_id == chat_id)
    if id:
        where = where.where(ChatMessage.id < int(id))
    with session_getter() as session:
        db_message = session.exec(where.order_by(ChatMessage.id.desc()).limit(page_size)).all()
    return resp_200(db_message)


@router.delete('/chat/{chat_id}', status_code=200)
def del_chat_id(*,
                request: Request,
                chat_id: str,
                login_user: UserPayload = Depends(get_login_user)):
    # 获取一条消息
    session_chat = MessageSessionDao.get_one(chat_id)

    if not session_chat or session_chat.is_delete:
        return resp_200(message='删除成功')

    session_chat.flow_id = session_chat.flow_id.replace('-','')
    # 处理临时数据
    col_name = f'tmp_{session_chat.flow_id}_{chat_id}'
    logger.info('tmp_delete_milvus col={}', col_name)
    delete_vector(col_name, None)
    delete_es(col_name)
    if session_chat.flow_type == FlowType.ASSISTANT.value:
        # DONE merge_check
        assistant_info = AssistantDao.get_one_assistant(session_chat.flow_id)
        # assistant_info = AssistantDao.get_one_assistant(UUID(session_chat.flow_id))
        if assistant_info:
            AuditLogService.delete_chat_assistant(login_user, get_request_ip(request), assistant_info)
    else:
        ChatMessageDao.delete_by_user_chat_id(login_user.user_id, chat_id)
        # 判断下是助手还是技能, 写审计日志
        flow_info = FlowDao.get_flow_by_id(session_chat.flow_id)
        if flow_info and flow_info.flow_type == FlowType.FLOW.value:
            AuditLogService.delete_chat_flow(login_user, get_request_ip(request), flow_info)
        elif flow_info:
            AuditLogService.delete_chat_workflow(login_user, get_request_ip(request), flow_info)

    # 设置会话的删除状态
    MessageSessionDao.delete_session(chat_id)

    return resp_200(message='删除成功')


@router.post('/chat/message', status_code=200)
def add_chat_messages(*,
                      request: Request,
                      data: AddChatMessages,
                      login_user: UserPayload = Depends(get_login_user)):
    """
    添加一条完整问答记录， 安全检查写入使用
    """
    logger.debug(f'gateway add_chat_messages {data}')
    flow_id = data.flow_id
    chat_id = data.chat_id
    if not chat_id or not flow_id:
        raise HTTPException(status_code=500, detail='chat_id 和 flow_id 必传参数')
    save_human_message = data.human_message
    flow_info = FlowDao.get_flow_by_id(flow_id)
    if flow_info and flow_info.flow_type == FlowType.WORKFLOW.value:
        # 工作流的输入，需要从输入里解析出来实际的输入内容
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
    # 更新会话的状态
    MessageSessionDao.update_sensitive_status(chat_id, SensitiveStatus.VIOLATIONS)

    # 写审计日志, 判断是否是新建会话
    session_info = MessageSessionDao.get_one(chat_id=chat_id)
    if not session_info:
        # 新建会话
        # 判断下是助手还是技能, 写审计日志
        if flow_info:
            MessageSessionDao.insert_one(MessageSession(
                chat_id=chat_id,
                flow_id=flow_id,
                flow_type=flow_info.flow_type,
                #flow_type = FlowType.FLOW.value,
                flow_name=flow_info.name,
                user_id=login_user.user_id,
                sensitive_status=SensitiveStatus.VIOLATIONS.value,
            ))
            if flow_info.flow_type == FlowType.FLOW.value:
                AuditLogService.create_chat_flow(login_user, get_request_ip(request), flow_id, flow_info)
            elif flow_info.flow_type == FlowType.WORKFLOW.value:
                AuditLogService.create_chat_workflow(login_user, get_request_ip(request), flow_id, flow_info)
            # AuditLogService.create_chat_flow(login_user, get_request_ip(request), flow_id.hex, flow_info)
        else:
            assistant_info = AssistantDao.get_one_assistant(flow_id)
            if assistant_info:
                MessageSessionDao.insert_one(MessageSession(
                    chat_id=chat_id,
                    flow_id=flow_id,
                    flow_type=FlowType.ASSISTANT.value,
                    flow_name=assistant_info.name,
                    user_id=login_user.user_id,
                    sensitive_status=SensitiveStatus.VIOLATIONS.value
                ))


                # AuditLogService.create_chat_assistant(login_user, get_request_ip(request), flow_id))
                AuditLogService.create_chat_assistant(login_user, get_request_ip(request),
                                                      flow_id, assistant_info)
                                                      # flow_id.hex, assistant_info)  # UUID check done

    return resp_200(data=message_dbs, message='添加成功')


@router.put('/chat/message/{message_id}', status_code=200)
def update_chat_message(*,
                        message_id: int,
                        message: str = Body(embed=True),
                        category: str = Body(default=None, embed=True),
                        login_user: UserPayload = Depends(get_login_user)):
    """ 更新一条消息的内容 安全检查使用"""
    logger.info(
        f'update_chat_message message_id={message_id} message={message} login_user={login_user.user_name}'
    )
    chat_message = ChatMessageDao.get_message_by_id(message_id)
    if not chat_message:
        return resp_200(message='消息不存在')
    if chat_message.user_id != login_user.user_id:
        return resp_200(message='用户不一致')

    chat_message.message = message
    if category:
        chat_message.category = category
    chat_message.source = False
    chat_message.sensitive_status = SensitiveStatus.VIOLATIONS.value

    ChatMessageDao.update_message_model(chat_message)

    MessageSessionDao.update_sensitive_status(chat_message.chat_id, SensitiveStatus.VIOLATIONS)

    return resp_200(message='更新成功')


@router.delete('/chat/message/{message_id}', status_code=200)
def del_message_id(*, message_id: str, login_user: UserPayload = Depends(get_login_user)):
    ChatMessageDao.delete_by_message_id(login_user.user_id, message_id)

    return resp_200(message='删除成功')


@router.post('/liked', status_code=200)
def like_response(*, data: ChatInput):
    message_id = data.message_id
    message = ChatMessageDao.get_message_by_id(data.message_id)
    if not message:
        raise NotFoundError.http_exception()

    if message.liked == data.liked:
        return resp_200(message='操作成功')

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

    # 更新会话表的点赞点踩数
    MessageSessionDao.add_like_count(message.chat_id, like_count)
    MessageSessionDao.add_dislike_count(message.chat_id, dislike_count)

    return resp_200(message='操作成功')


@router.post('/chat/copied', status_code=200)
def copied_message(message_id: int = Body(embed=True)):
    """ 上传复制message的数据 """
    message = ChatMessageDao.get_message_by_id(message_id)
    if not message:
        raise NotFoundError.http_exception()
    if message.copied != 1:
        ChatMessageDao.update_message_copied(message_id, 1)
        MessageSessionDao.add_copied_count(message.chat_id, 1)
    return resp_200(message='操作成功')


@router.post('/chat/comment', status_code=200)
def comment_resp(*, data: ChatInput):
    comment_answer(data.message_id, data.comment)
    return resp_200(message='操作成功')


@router.get('/chat/list')
def get_session_list(*,
                     page: Optional[int] = 1,
                     limit: Optional[int] = 10,
                     flow_type: Optional[int] = None,
                     login_user: UserPayload = Depends(get_login_user)):
    res = MessageSessionDao.filter_session(user_ids=[login_user.user_id],
                                           flow_type=flow_type,
                                           page=page,
                                           limit=limit,
                                           include_delete=False)
    chat_ids = []
    flow_ids = []
    for one in res:
        chat_ids.append(one.chat_id)
        flow_ids.append(one.flow_id)
    flow_list = FlowDao.get_flow_by_ids(flow_ids)
#<<<<<<< HEAD
    # DONE merge_check
    assistant_list = AssistantDao.get_assistants_by_ids(flow_ids)
    logo_map = {one.id: BaseService.get_logo_share_link(one.logo) for one in flow_list}
    logo_map.update({one.id: BaseService.get_logo_share_link(one.logo) for one in assistant_list})
    latest_messages = ChatMessageDao.get_latest_message_by_chat_ids(chat_ids,
                                                                     exclude_category=WorkflowEventType.UserInput.value)
#=======
    # assistant_list = AssistantDao.get_assistants_by_ids([UUID(one.replace("-",'')) for one in flow_ids])
    # logo_map = {one.id.hex: BaseService.get_logo_share_link(one.logo) for one in flow_list}
    # logo_map.update({one.id.hex: BaseService.get_logo_share_link(one.logo) for one in assistant_list})
    # latest_messages = ChatMessageDao.get_latest_message_by_chat_ids(chat_ids, category='user_input')
#>>>>>>> feat/zyrs_0527
    latest_messages = {one.chat_id: one for one in latest_messages}
    return resp_200([
        ChatList(
            chat_id=one.chat_id,
            flow_id=one.flow_id,
            flow_name=one.flow_name,
            flow_type=one.flow_type,
#<<<<<<< HEAD
            # DONE merge_check
#            logo=logo_map.get(one.flow_id, ''),
#=======
            logo=logo_map.get(one.flow_id.replace("-",''), ''),
#>>>>>>> feat/zyrs_0527
            latest_message=latest_messages.get(one.chat_id, None),
            create_time=one.create_time,
            update_time=one.update_time) for one in res
    ])


# 获取所有已上线的技能和助手
@router.get('/chat/online')
def get_online_chat(*,
                    keyword: Optional[str] = None,
                    tag_id: Optional[int] = None,
                    page: Optional[int] = 1,
                    limit: Optional[int] = 10,
                    user: UserPayload = Depends(get_login_user)):
    data, _ = WorkFlowService.get_all_flows(user, keyword, FlowStatus.ONLINE.value, tag_id, None, page, limit)
    return resp_200(data=data)


@router.websocket('/chat/{flow_id}')
async def chat(
        *,
        flow_id: UUID,
        websocket: WebSocket,
        t: Optional[str] = None,
        chat_id: Optional[str] = None,
        version_id: Optional[int] = None,
        Authorize: AuthJWT = Depends(),
):
    """Websocket endpoint for chat."""
    flow_id = flow_id.hex  # UUID check done
    try:
        if t:
            Authorize.jwt_required(auth_from='websocket', token=t)
            Authorize._token = t
        else:
            Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        login_user = await get_login_user(Authorize)
        user_id = login_user.user_id
        if chat_id:
            with session_getter() as session:
                db_flow = session.get(Flow, flow_id)
            if not db_flow:
                await websocket.accept()
                message = '该技能已被删除'
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
            if db_flow.status != 2:
                await websocket.accept()
                message = '当前技能未上线，无法直接对话'
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
            graph_data = db_flow.data
        else:
            flow_data_key = 'flow_data_' + flow_id
            if version_id:
                flow_data_key = flow_data_key + '_' + str(version_id)
            if not flow_data_store.exists(flow_data_key) or str(
                    flow_data_store.hget(flow_data_key, 'status'),
                    'utf-8') != BuildStatus.SUCCESS.value:
                await websocket.accept()
                message = '当前编译没通过'
                await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason=message)
                return
            graph_data = json.loads(flow_data_store.hget(flow_data_key, 'graph_data'))

        if not chat_id:
            # 调试时，每次都初始化对象
            chat_manager.set_cache(get_cache_key(flow_id, chat_id), None)

        with logger.contextualize(trace_id=chat_id):
            logger.info('websocket_verify_ok begin=handle_websocket')
            await chat_manager.handle_websocket(flow_id,
                                                chat_id,
                                                websocket,
                                                user_id,
                                                gragh_data=graph_data)
    except WebSocketException as exc:
        logger.error(f'Websocket exrror: {str(exc)}')
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as exc:
        logger.exception(f'Error in chat websocket: {str(exc)}')
        messsage = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if 'Could not validate credentials' in str(exc):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason='Unauthorized')
        else:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=messsage)


@router.post('/build/init/{flow_id}')
async def init_build(*,
                     graph_data: dict,
                     flow_id: str,
                     version_id: Optional[int] = Query(default=None, description='技能版本ID')):
    """Initialize the build by storing graph data and returning a unique session ID."""
    chat_id = graph_data.get('chat_id')
    flow_data_key = 'flow_data_' + flow_id

    if chat_id:
        with session_getter() as session:
            graph_data = session.get(Flow, flow_id).data
    elif version_id:
        flow_data_key = flow_data_key + '_' + str(version_id)
        graph_data = FlowVersionDao.get_version_by_id(version_id).data
    try:
        if flow_id is None:
            raise ValueError('No ID provided')
        # Check if already building
        if flow_data_store.hget(flow_data_key, 'status') == BuildStatus.IN_PROGRESS.value:
            return resp_200(InitResponse(flowId=flow_id))

        # Delete from cache if already exists
        flow_data_store.hset(flow_data_key,
                             mapping={
                                 'graph_data': json.dumps(graph_data),
                                 'status': BuildStatus.STARTED.value
                             },
                             expiration=expire)

        return resp_200(InitResponse(flowId=flow_id))
    except Exception as exc:
        logger.error(exc)
        return HTTPException(status_code=500, detail=str(exc))


@router.get('/build/{flow_id}/status', response_model=UnifiedResponseModel[BuiltResponse])
async def build_status(flow_id: str,
                       chat_id: Optional[str] = None,
                       version_id: Optional[int] = Query(default=None, description='技能版本ID')):
    """Check the flow_id is in the flow_data_store."""
    try:
        flow_data_key = 'flow_data_' + flow_id
        if not chat_id and version_id:
            flow_data_key = flow_data_key + '_' + str(version_id)
        built = (flow_data_store.hget(flow_data_key, 'status') == BuildStatus.SUCCESS.value)
        return resp_200(BuiltResponse(built=built, ))

    except Exception as exc:
        logger.error(exc)
        return HTTPException(status_code=500, detail=str(exc))


@router.get('/build/stream/{flow_id}', response_class=StreamingResponse)
async def stream_build(flow_id: str,
                       chat_id: Optional[str] = None,
                       version_id: Optional[int] = Query(default=None, description='技能版本ID')):
    """Stream the build process based on stored flow data."""

    async def event_stream(flow_id, chat_id: str, version_id: Optional[int] = None):
        final_response = {'end_of_stream': True}
        artifacts = {}
        try:
            flow_data_key = 'flow_data_' + flow_id
            if not chat_id and version_id:
                flow_data_key = flow_data_key + '_' + str(version_id)
            if not flow_data_store.exists(flow_data_key):
                error_message = 'Invalid session ID'
                yield str(StreamData(event='error', data={'error': error_message}))
                return

            if flow_data_store.hget(flow_data_key, 'status') == BuildStatus.IN_PROGRESS.value:
                error_message = 'Already building'
                yield str(StreamData(event='error', data={'error': error_message}))
                return

            graph_data = json.loads(flow_data_store.hget(flow_data_key, 'graph_data'))

            if not graph_data:
                error_message = 'No data provided'
                yield str(StreamData(event='error', data={'error': error_message}))
                return

            logger.debug('Building langchain object')
            flow_data_store.hsetkey(flow_data_key, 'status', BuildStatus.IN_PROGRESS.value, expire)

            # L1 用户，采用build流程
            try:
                async for message in build_flow(graph_data=graph_data,
                                                artifacts=artifacts,
                                                process_file=False,
                                                flow_id=flow_id,
                                                chat_id=chat_id):
                    if isinstance(message, Graph):
                        graph = message
                    else:
                        yield message

            except Exception as e:
                logger.error(f'Build flow error: {e}')
                flow_data_store.hsetkey(flow_data_key,
                                        'status',
                                        BuildStatus.FAILURE.value,
                                        expiration=expire)
                yield str(StreamData(event='error', data={'error': str(e)}))
                return

            await graph.abuild()
            # Now we  need to check the input_keys to send them to the client
            input_keys_response = {
                'input_keys': [],
                'memory_keys': [],
                'handle_keys': [],
            }
            input_nodes = graph.get_input_nodes()
            for node in input_nodes:
                if hasattr(await node.get_result(), 'input_keys'):
                    input_keys = build_input_keys_response(await node.get_result(), artifacts)
                    input_keys['input_keys'].update({'id': node.id})
                    input_keys_response['input_keys'].append(input_keys.get('input_keys'))
                    input_keys_response['memory_keys'].extend(input_keys.get('memory_keys'))
                    input_keys_response['handle_keys'].extend(input_keys.get('handle_keys'))
                elif ('fileNode' in node.output):
                    input_keys_response['input_keys'].append({
                        'file_path': '',
                        'type': 'file',
                        'id': node.id
                    })

            yield str(StreamData(event='message', data=input_keys_response))
            # We need to reset the chat history
            chat_manager.chat_history.empty_history(flow_id, chat_id)
            chat_manager.set_cache(get_cache_key(flow_id=flow_id, chat_id=chat_id), None)
            flow_data_store.hsetkey(flow_data_key, 'status', BuildStatus.SUCCESS.value, expire)
        except Exception as exc:
            logger.exception(exc)
            logger.error('Error while building the flow: %s', exc)
            flow_data_store.hsetkey(flow_data_key, 'status', BuildStatus.FAILURE.value, expire)
            yield str(StreamData(event='error', data={'error': str(exc)}))
        finally:
            yield str(StreamData(event='message', data=final_response))

    try:
        return StreamingResponse(event_stream(flow_id, chat_id, version_id),
                                 media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        raise HTTPException(status_code=500, detail=str(exc))
