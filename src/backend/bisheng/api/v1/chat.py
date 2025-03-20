import json
from typing import List, Optional
from uuid import UUID, uuid1

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
                                    ChatList, FlowGptsOnlineList, InitResponse, StreamData,
                                    UnifiedResponseModel, resp_200)
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.database.base import session_getter
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.mark_record import MarkRecordDao
from bisheng.database.models.mark_task import MarkTaskDao
from bisheng.database.models.message import ChatMessage, ChatMessageDao, ChatMessageRead, MessageDao, LikedType
from bisheng.database.models.session import SensitiveStatus, MessageSessionDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.graph.graph.base import Graph
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key
from fastapi import (APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketException,
                     status)
from fastapi.params import Depends
from fastapi.responses import StreamingResponse
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import func
from sqlmodel import select

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
    session_id = request.session_id or uuid1().hex

    payload = {'user_name': 'root', 'user_id': 1, 'role': 'admin'}
    access_token = Authorize.create_access_token(subject=json.dumps(payload), expires_time=864000)
    url = f'ws://127.0.0.1:7860/api/v1/chat/{request.model}?chat_id={session_id}&t={access_token}'
    web_conn = await chat_imp.get_connection(url, session_id)

    return StreamingResponse(chat_imp.event_stream(web_conn, message, session_id, request.model,
                                                   request.streaming),
                             media_type='text/event-stream')


@router.get('/chat/app/list',
            response_model=UnifiedResponseModel[PageList[AppChatList]],
            status_code=200)
def get_app_chat_list(*,
                      keyword: Optional[str] = None,
                      mark_user: Optional[str] = None,
                      mark_status: Optional[int] = None,
                      task_id: Optional[int] = None,
                      page_num: Optional[int] = 1,
                      page_size: Optional[int] = 20,
                      login_user: UserPayload = Depends(get_login_user)):
    """通过消息表进行聊天App统计，全量表查询
    性能问题后续优化"""

    group_flow_ids = []
    flow_ids, user_ids = [], []

    user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
    if not task_id:
        # task_list = MarkTaskDao.get_all_task(page_size=page_size,page_num=page_num);
        # group_flow_ids = [app_id for one in task_list[0] for app_id in one.app_id.split(",")]
        group_flow_ids = []
    else:
        if not login_user.is_admin():
            task = MarkTaskDao.get_task_byid(task_id)
            if str(login_user.user_id) not in task.process_users.split(','):
                raise HTTPException(status_code=403, detail='没有权限')
            # 判断下是否是用户组管理员
            if user_groups:
                task = MarkTaskDao.get_task_byid(task_id)
                # TODO: 加入筛选条件
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
            #flow_ids = list(set(flow_ids) & set(group_flow_ids))
            flow_ids = flow_ids
        else:
            flow_ids = group_flow_ids

    res, count = MessageDao.app_list_group_by_chat_id(page_size=page_size,
                                                      page_num=page_num,
                                                      flow_ids=flow_ids,
                                                      user_ids=user_ids)
    # 补齐中文
    user_ids = [one.get('user_id') for one in res]
    flow_ids = [one.get('flow_id') for one in res]
    user_list = UserDao.get_user_by_ids(user_ids)
    flow_list = FlowDao.get_flow_by_ids(flow_ids)
    assistant_list = AssistantDao.get_assistants_by_ids(flow_ids)
    user_map = {user.user_id: user.user_name for user in user_list}
    flow_map = {flow.id: flow for flow in flow_list}
    assistant_map = {assistant.id: assistant for assistant in assistant_list}

    flow_map.update(assistant_map)
    res_obj = PageList(list=[
        AppChatList(user_name=user_map.get(one['user_id'], one['user_id']),
                    flow_name=flow_map[one['flow_id']].name if flow_map.get(one['flow_id']) else one['flow_id'],
                    flow_type=FlowType.ASSISTANT.value if assistant_map.get(one['flow_id'], None) else flow_map[one['flow_id']].flow_type,
                    **one) for one in res if flow_map.get(one['flow_id'])
    ],
                       total=count)

    for o in res_obj.list:
        mark = MarkRecordDao.get_record(task_id, o.chat_id)
        o.mark_user = ''
        o.mark_status = 1
        if mark:
            o.mark_user = mark.create_user if mark.create_user is not None else ''
            o.mark_status = mark.status if mark.status is not None else 1
            o.mark_id = mark.create_id

    if mark_status:
        res_obj.list = [one for one in res_obj.list if one.mark_status == mark_status]
        res_obj.total = len(res_obj.list)

    if mark_user:
        users = mark_user.split(',')
        users_int = [int(user) for user in users]
        res_obj.list = [one for one in res_obj.list if one.mark_id in users_int]
        res_obj.total = len(res_obj.list)

    # if not user_groups and not login_user.is_admin():
    #     res_obj.list = [one for one in res_obj.list if one.mark_id==login_user.user_id]
    #     res_obj.total = len(res_obj.list)

    return resp_200(res_obj)


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
    message = ChatMessageDao.get_latest_message_by_chatid(chat_id)
    if message:
        # 处理临时数据
        col_name = f'tmp_{message.flow_id.hex}_{chat_id}'
        logger.info('tmp_delete_milvus col={}', col_name)
        delete_vector(col_name, None)
        delete_es(col_name)
        ChatMessageDao.delete_by_user_chat_id(login_user.user_id, chat_id)
        # 判断下是助手还是技能, 写审计日志
        flow_info = FlowDao.get_flow_by_id(message.flow_id.hex)
        if flow_info:
            if flow_info.flow_type == FlowType.FLOW.value:
                AuditLogService.delete_chat_flow(login_user, get_request_ip(request), flow_info)
            else:
                AuditLogService.delete_chat_workflow(login_user, get_request_ip(request), flow_info)
        else:
            assistant_info = AssistantDao.get_one_assistant(message.flow_id)
            if assistant_info:
                AuditLogService.delete_chat_assistant(login_user, get_request_ip(request),
                                                      assistant_info)

    return resp_200(message='删除成功')


@router.post('/chat/message', status_code=200)
def add_chat_messages(*,
                      request: Request,
                      data: AddChatMessages,
                      login_user: UserPayload = Depends(get_login_user)):
    """
    添加一条完整问答记录， 安全检查写入使用
    """
    flow_id = data.flow_id
    chat_id = data.chat_id
    if not chat_id or not flow_id:
        raise HTTPException(status_code=500, detail='chat_id 和 flow_id 必传参数')
    human_message = ChatMessage(flow_id=flow_id.hex,
                                chat_id=chat_id,
                                user_id=login_user.user_id,
                                is_bot=False,
                                message=data.human_message,
                                sensitive_status=SensitiveStatus.VIOLATIONS.value,
                                type='human',
                                category='question')
    bot_message = ChatMessage(flow_id=flow_id.hex,
                              chat_id=chat_id,
                              user_id=login_user.user_id,
                              is_bot=True,
                              message=data.answer_message,
                              sensitive_status=SensitiveStatus.VIOLATIONS.value,
                              type='bot',
                              category='answer')
    ChatMessageDao.insert_batch([human_message, bot_message])
    # 更新会话的状态
    MessageSessionDao.update_sensitive_status(chat_id, SensitiveStatus.VIOLATIONS)

    # 写审计日志, 判断是否是新建会话
    res = ChatMessageDao.get_messages_by_chat_id(chat_id=chat_id)
    if len(res) <= 2:
        # 新建会话
        # 判断下是助手还是技能, 写审计日志
        flow_info = FlowDao.get_flow_by_id(flow_id.hex)
        if flow_info:
            AuditLogService.create_chat_flow(login_user, get_request_ip(request), flow_id.hex, flow_info)
        else:
            assistant_info = AssistantDao.get_one_assistant(flow_id)
            if assistant_info:
                AuditLogService.create_chat_assistant(login_user, get_request_ip(request),
                                                      flow_id.hex)

    return resp_200(message='添加成功')


@router.put('/chat/message/{message_id}', status_code=200)
def update_chat_message(*,
                        message_id: int,
                        message: str = Body(embed=True),
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
    chat_message.source = False

    ChatMessageDao.update_message_model(chat_message)

    return resp_200(message='更新成功')


@router.delete('/chat/message/{message_id}', status_code=200)
def del_message_id(*, message_id: str, login_user: UserPayload = Depends(get_login_user)):
    # 获取一条消息
    ChatMessageDao.delete_by_message_id(login_user.user_id, message_id)

    return resp_200(message='删除成功')


@router.post('/liked', status_code=200)
def like_response(*, data: ChatInput, login_user: UserPayload = Depends(get_login_user)):
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
def copied_message(*,
                   message_id: int = Body(embed=True),
                   login_user: UserPayload = Depends(get_login_user)):
    """ 上传复制message的数据 """
    message = ChatMessageDao.get_message_by_id(message_id)
    if not message:
        raise NotFoundError.http_exception()
    if message.copied != 1:
        ChatMessageDao.update_message_copied(message_id, 1)
        MessageSessionDao.add_copied_count(message.chat_id, 1)
    return resp_200(message='操作成功')


@router.post('/chat/comment', status_code=200)
def comment_resp(*, data: ChatInput, login_user: UserPayload = Depends(get_login_user)):
    comment_answer(data.message_id, data.comment)
    return resp_200(message='操作成功')


@router.get('/chat/list', response_model=UnifiedResponseModel[List[ChatList]], status_code=200)
def get_session_list(*,
                      page: Optional[int] = 1,
                      limit: Optional[int] = 10,
                      login_user: UserPayload = Depends(get_login_user)):

    res = MessageSessionDao.filter_session(user_ids=[login_user.user_id], page=page, limit=limit, include_delete=False)
    chat_ids = []
    flow_ids = []
    for one in res:
        chat_ids.append(one.chat_id)
        flow_ids.append(one.flow_id)
    flow_list = FlowDao.get_flow_by_ids(flow_ids)
    assistant_list = AssistantDao.get_assistants_by_ids(flow_ids)
    logo_map = {one.id.hex: BaseService.get_logo_share_link(one.logo) for one in flow_list}
    logo_map.update({one.id.hex: BaseService.get_logo_share_link(one.logo) for one in assistant_list})
    latest_messages = ChatMessageDao.get_latest_message_by_chat_ids(chat_ids,
                                                                    exclude_category=WorkflowEventType.UserInput.value)
    latest_messages = {one.chat_id: one for one in latest_messages}
    return resp_200([
        ChatList(
            chat_id=one.chat_id,
            flow_id=one.flow_id,
            flow_name=one.flow_name,
            flow_type=one.flow_type,
            logo=logo_map.get(one.flow_id, ''),
            latest_message=latest_messages.get(one.chat_id, None),
            create_time=one.create_time,
            update_time=one.update_time) for one in res
    ])


# 获取所有已上线的技能和助手
@router.get('/chat/online',
            response_model=UnifiedResponseModel[List[FlowGptsOnlineList]],
            status_code=200)
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
        flow_id: str,
        websocket: WebSocket,
        t: Optional[str] = None,
        chat_id: Optional[str] = None,
        version_id: Optional[int] = None,
        Authorize: AuthJWT = Depends(),
):
    """Websocket endpoint for chat."""
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


@router.post('/build/init/{flow_id}',
             response_model=UnifiedResponseModel[InitResponse],
             status_code=201)
async def init_build(*,
                     graph_data: dict,
                     flow_id: str,
                     version_id: Optional[int] = Query(default=None, description='技能版本ID')):
    """Initialize the build by storing graph data and returning a unique session ID."""
    chat_id = graph_data.get('chat_id')
    flow_data_key = 'flow_data_' + flow_id

    if chat_id:
        with session_getter() as session:
            graph_data = session.get(Flow, UUID(flow_id).hex).data
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
                                                flow_id=UUID(flow_id).hex,
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
