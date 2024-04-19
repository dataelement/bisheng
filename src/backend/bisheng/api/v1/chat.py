import json
from typing import List, Optional
from uuid import UUID

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.services.knowledge_imp import delete_es, delete_vector
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import build_flow, build_input_keys_response
from bisheng.api.v1.schemas import (BuildStatus, BuiltResponse, ChatInput, ChatList,
                                    FlowGptsOnlineList, InitResponse, StreamData,
                                    UnifiedResponseModel, resp_200)
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.database.base import session_getter
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.message import ChatMessage, ChatMessageDao, ChatMessageRead
from bisheng.graph.graph.base import Graph
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketException, status
from fastapi.params import Depends
from fastapi.responses import StreamingResponse
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import func
from sqlmodel import select

router = APIRouter(tags=['Chat'])
chat_manager = ChatManager()
flow_data_store = redis_client
expire = 600  # reids 60s 过期


@router.get('/chat/history',
            response_model=UnifiedResponseModel[List[ChatMessageRead]],
            status_code=200)
def get_chatmessage(*,
                    chat_id: str,
                    flow_id: str,
                    id: Optional[str] = None,
                    page_size: Optional[int] = 20,
                    Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    if not chat_id or not flow_id:
        return {'code': 500, 'message': 'chat_id 和 flow_id 必传参数'}
    where = select(ChatMessage).where(ChatMessage.flow_id == flow_id,
                                      ChatMessage.chat_id == chat_id,
                                      ChatMessage.user_id == payload.get('user_id'))
    if id:
        where = where.where(ChatMessage.id < int(id))
    with session_getter() as session:
        db_message = session.exec(where.order_by(ChatMessage.id.desc()).limit(page_size)).all()
    return resp_200(db_message)


@router.delete('/chat/{chat_id}', status_code=200)
def del_chat_id(*, chat_id: str, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    # 获取一条消息
    message = ChatMessageDao.get_latest_message_by_chatid(chat_id)
    if message:
        # 处理临时数据
        col_name = f'tmp_{message.flow_id.hex}_{chat_id}'
        logger.info('tmp_delete_milvus col={}', col_name)
        delete_vector(col_name, None)
        delete_es(col_name)
        ChatMessageDao.delete_by_user_chat_id(payload.get('user_id'), chat_id)

    return resp_200(message='删除成功')


@router.post('/liked', status_code=200)
def like_response(*, data: ChatInput, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    message_id = data.message_id
    liked = data.liked
    with session_getter() as session:
        message = session.get(ChatMessage, message_id)
    if message:
        logger.info('act=add_liked user_id={} liked={}', payload.get('user_id'), liked)
        message.liked = liked
    with session_getter() as session:
        session.add(message)
        session.commit()
    return resp_200(message='操作成功')


@router.post('/chat/comment', status_code=200)
def comment_resp(*, data: ChatInput, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    comment_answer(data.message_id, data.comment)
    return resp_200(message='操作成功')


@router.get('/chat/list', response_model=UnifiedResponseModel[List[ChatList]], status_code=200)
def get_chatlist_list(*, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    smt = (select(ChatMessage.flow_id, ChatMessage.chat_id,
                  func.max(ChatMessage.create_time).label('create_time'),
                  func.max(ChatMessage.update_time).label('update_time')).where(
                      ChatMessage.user_id == payload.get('user_id')).group_by(
                          ChatMessage.flow_id,
                          ChatMessage.chat_id).order_by(func.max(ChatMessage.create_time).desc()))
    with session_getter() as session:
        db_message = session.exec(smt).all()
    flow_ids = [message.flow_id for message in db_message]
    with session_getter() as session:
        db_flow = session.exec(select(Flow).where(Flow.id.in_(flow_ids))).all()

    assistant_chats = AssistantDao.get_assistants_by_ids(flow_ids)
    assistant_dict = {assistant.id: assistant for assistant in assistant_chats}
    # set object
    chat_list = []
    flow_dict = {flow.id: flow for flow in db_flow}
    for i, message in enumerate(db_message):
        if message.flow_id in flow_dict:
            chat_list.append(
                ChatList(flow_name=flow_dict[message.flow_id].name,
                         flow_description=flow_dict[message.flow_id].description,
                         flow_id=message.flow_id,
                         flow_type='flow',
                         chat_id=message.chat_id,
                         create_time=message.create_time,
                         update_time=message.update_time))
        elif message.flow_id in assistant_dict:
            chat_list.append(
                ChatList(flow_name=assistant_dict[message.flow_id].name,
                         flow_description=assistant_dict[message.flow_id].desc,
                         flow_id=message.flow_id,
                         chat_id=message.chat_id,
                         flow_type='assistant',
                         create_time=message.create_time,
                         update_time=message.update_time))
        else:
            # 通过接口创建的会话记录，不关联技能或者助手
            logger.debug(f'unknown message.flow_id={message.flow_id}')
    return resp_200(chat_list)


# 获取所有已上线的技能和助手
@router.get('/chat/online', response_model=UnifiedResponseModel[List[FlowGptsOnlineList]], status_code=200)
def get_online_chat(*, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**payload)
    user_id = user.user_id
    res = []
    # 获取所有已上线的助手
    if user.is_admin():
        all_assistant = AssistantDao.get_all_online_assistants()
        flows = FlowDao.get_all_online_flows()
    else:
        assistants = AssistantService.get_assistant(user, None, AssistantStatus.ONLINE.value, 0, 0)
        all_assistant = assistants.data.get('data')
        flows = FlowDao.get_user_access_online_flows(user_id)
    for one in all_assistant:
        res.append(
            FlowGptsOnlineList(
                id=one.id.hex,
                name=one.name,
                desc=one.desc,
                create_time=one.create_time,
                update_time=one.update_time,
                flow_type='assistant'
            )
        )

    # 获取用户可见的所有已上线的技能
    for one in flows:
        res.append(
            FlowGptsOnlineList(
                id=one.id.hex,
                name=one.name,
                desc=one.description,
                create_time=one.create_time,
                update_time=one.update_time,
                flow_type='flow'
            )
        )
    res.sort(key=lambda x: x.update_time, reverse=True)
    return resp_200(data=res)


@router.websocket('/chat/{flow_id}')
async def chat(
        *,
        flow_id: str,
        websocket: WebSocket,
        t: Optional[str] = None,
        chat_id: Optional[str] = None,
        Authorize: AuthJWT = Depends(),
):
    """Websocket endpoint for chat."""
    try:
        if t:
            Authorize.jwt_required(auth_from='websocket', token=t)
            Authorize._token = t
        else:
            Authorize.jwt_required(auth_from='websocket', websocket=websocket)

        payload = Authorize.get_jwt_subject()
        payload = json.loads(payload)
        user_id = payload.get('user_id')
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
async def init_build(*, graph_data: dict, flow_id: str):
    """Initialize the build by storing graph data and returning a unique session ID."""
    chat_id = graph_data.get('chat_id')
    if chat_id:
        with session_getter() as session:
            graph_data = session.get(Flow, UUID(flow_id).hex).data

    try:
        if flow_id is None:
            raise ValueError('No ID provided')
        # Check if already building
        flow_data_key = 'flow_data_' + flow_id
        if flow_data_store.hget(flow_data_key, 'status') == BuildStatus.IN_PROGRESS.value:
            return resp_200(InitResponse(flowId=flow_id))

        # Delete from cache if already exists
        flow_data_store.hset(flow_data_key,
                             map={
                                 'graph_data': json.dumps(graph_data),
                                 'status': BuildStatus.STARTED.value
                             },
                             expiration=expire)

        return resp_200(InitResponse(flowId=flow_id))
    except Exception as exc:
        logger.error(exc)
        return HTTPException(status_code=500, detail=str(exc))


@router.get('/build/{flow_id}/status', response_model=UnifiedResponseModel[BuiltResponse])
async def build_status(flow_id: str):
    """Check the flow_id is in the flow_data_store."""
    try:
        flow_data_key = 'flow_data_' + flow_id
        built = (flow_data_store.hget(flow_data_key, 'status') == BuildStatus.SUCCESS.value)
        return resp_200(BuiltResponse(built=built, ))

    except Exception as exc:
        logger.error(exc)
        return HTTPException(status_code=500, detail=str(exc))


@router.get('/build/stream/{flow_id}', response_class=StreamingResponse)
async def stream_build(flow_id: str, chat_id: Optional[str] = None):
    """Stream the build process based on stored flow data."""

    async def event_stream(flow_id, chat_id: str):
        final_response = {'end_of_stream': True}
        artifacts = {}
        try:
            flow_data_key = 'flow_data_' + flow_id
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
        return StreamingResponse(event_stream(flow_id, chat_id), media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        raise HTTPException(status_code=500, detail=str(exc))
