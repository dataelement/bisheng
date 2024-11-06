import asyncio
import concurrent.futures
import json
import time
import uuid
from collections import defaultdict
from queue import Queue
from typing import Any, Dict, List
from uuid import UUID

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import build_flow_no_yield, get_request_ip
from bisheng.api.v1.schemas import ChatMessage, ChatResponse, FileResponse
from bisheng.cache import cache_manager
from bisheng.cache.flow import InMemoryCache
from bisheng.cache.manager import Subject
from bisheng.chat.client import ChatClient
from bisheng.chat.clients.workflow_client import WorkflowClient
from bisheng.chat.types import IgnoreException, WorkType
from bisheng.chat.utils import process_node_data
from bisheng.database.base import session_getter
from bisheng.database.models.flow import Flow
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.user import User, UserDao
from bisheng.graph.utils import find_next_node
from bisheng.processing.process import process_tweaks
from bisheng.utils.threadpool import ThreadPoolManager, thread_pool
from bisheng.utils.util import get_cache_key
from bisheng_langchain.input_output.output import Report
from fastapi import Request, WebSocket, WebSocketDisconnect, status
from loguru import logger


class ChatHistory(Subject):

    def __init__(self):
        super().__init__()
        self.history: Dict[str, List[ChatMessage]] = defaultdict(list)

    def add_message(
        self,
        client_id: str,
        chat_id: str,
        message: ChatMessage,
    ):
        """Add a message to the chat history."""
        t1 = time.time()
        from bisheng.database.models.message import ChatMessage
        message.flow_id = client_id
        message.chat_id = chat_id
        if chat_id and (message.message or message.intermediate_steps
                        or message.files) and message.type != 'stream':
            msg = message.copy()
            msg.message = json.dumps(msg.message) if isinstance(msg.message, dict) else msg.message
            files = json.dumps(msg.files) if msg.files else ''
            msg.__dict__.pop('files')
            db_message = ChatMessage(files=files, **msg.__dict__)
            logger.info(f'chat={db_message} time={time.time() - t1}')
            with session_getter() as seesion:
                seesion.add(db_message)
                seesion.commit()
                seesion.refresh(db_message)
                message.message_id = db_message.id

        if not isinstance(message, FileResponse):
            self.notify()

    def empty_history(self, client_id: str, chat_id: str):
        """Empty the chat history for a client."""
        self.history[get_cache_key(client_id, chat_id)] = []


class ChatManager:

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.chat_history = ChatHistory()
        self.cache_manager = cache_manager
        self.cache_manager.attach(self.update)
        self.in_memory_cache = InMemoryCache()
        self.task_manager: List[asyncio.Task] = []
        # 已连接的客户端
        self.active_clients: Dict[str, ChatClient] = {}

        # 记录流式输出结果
        self.stream_queue: Dict[str, Queue] = {}

    def update(self):
        if self.cache_manager.current_client_id in self.active_connections:
            self.last_cached_object_dict = self.cache_manager.get_last()
            # Add a new ChatResponse with the data
            chat_response = FileResponse(
                message=None,
                type='file',
                data=self.last_cached_object_dict['obj'],
                data_type=self.last_cached_object_dict['type'],
            )

            self.chat_history.add_message(self.cache_manager.current_client_id,
                                          self.cache_manager.current_chat_id, chat_response)

    async def connect(self, client_id: str, chat_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[get_cache_key(client_id, chat_id)] = websocket
        self.stream_queue[get_cache_key(client_id, chat_id)] = Queue()

    def reuse_connect(self, client_id: str, chat_id: str, websocket: WebSocket):
        self.active_connections[get_cache_key(client_id, chat_id)] = websocket
        self.stream_queue[get_cache_key(client_id, chat_id)] = Queue()

    def disconnect(self, client_id: str, chat_id: str, key: str = None):
        if key:
            logger.debug('disconnect_ws key={}', key)
            self.active_connections.pop(key, None)
        else:
            logger.info('disconnect_ws key={}', get_cache_key(client_id, chat_id))
            self.active_connections.pop(get_cache_key(client_id, chat_id), None)

    async def send_message(self, client_id: str, chat_id: str, message: str):
        websocket = self.active_connections[get_cache_key(client_id, chat_id)]
        await websocket.send_text(message)

    async def send_json(self, client_id: str, chat_id: str, message: ChatMessage, add=True):
        message.flow_id = client_id
        message.chat_id = chat_id
        websocket = self.active_connections[get_cache_key(client_id, chat_id)]
        # 增加消息记录
        if add:
            self.chat_history.add_message(client_id, chat_id, message)
        await websocket.send_json(message.dict())

    async def close_connection(self,
                               flow_id: str,
                               chat_id: str,
                               code: int,
                               reason: str,
                               key_list: List[str] = None):
        """close and clean ws"""
        if websocket := self.active_connections[get_cache_key(flow_id, chat_id)]:
            try:
                await websocket.close(code=code, reason=reason)
                self.disconnect(flow_id, chat_id)
                if key_list:
                    for key in key_list:
                        self.disconnect(flow_id, chat_id, key)
            except RuntimeError as exc:
                # This is to catch the following error:
                #  Unexpected ASGI message 'websocket.close', after sending 'websocket.close'
                if 'after sending' in str(exc):
                    logger.error(exc)

    async def ping(self, client_id: str, chat_id: str):
        ping_pong = ChatMessage(
            is_bot=True,
            message='pong',
            intermediate_steps='',
        )
        await self.send_json(client_id, chat_id, ping_pong, False)

    def set_cache(self, client_id: str, langchain_object: Any) -> bool:
        """
        Set the cache for a client.
        """

        self.in_memory_cache.set(client_id, langchain_object)
        return client_id in self.in_memory_cache

    async def accept_client(self, client_key: str, chat_client: ChatClient, websocket: WebSocket):
        await websocket.accept()
        self.active_clients[client_key] = chat_client

    def clear_client(self, client_key: str):
        if client_key not in self.active_clients:
            logger.warning('close_client client_key={} not in active_clients', client_key)
            return
        logger.info('close_client client_key={}', client_key)
        self.active_clients.pop(client_key, None)

    async def close_client(self, client_key: str, code: int, reason: str):
        if chat_client := self.active_clients.get(client_key):
            try:
                await chat_client.websocket.close(code=code, reason=reason)
                self.clear_client(client_key)
            except RuntimeError as exc:
                # This is to catch the following error:
                #  Unexpected ASGI message 'websocket.close', after sending 'websocket.close'
                if 'after sending' in str(exc):
                    logger.error(exc)

    async def dispatch_client(
            self,
            request: Request,  # 原始请求体
            client_id: str,
            chat_id: str,
            login_user: UserPayload,
            work_type: WorkType,
            websocket: WebSocket,
            graph_data: dict = None):
        client_key = uuid.uuid4().hex
        if work_type == WorkType.GPTS:
            chat_client = ChatClient(request,
                                     client_key,
                                     client_id,
                                     chat_id,
                                     login_user.user_id,
                                     login_user,
                                     work_type,
                                     websocket,
                                     graph_data=graph_data)
        else:
            chat_client = WorkflowClient(request,
                                         client_key,
                                         client_id,
                                         chat_id,
                                         login_user.user_id,
                                         login_user,
                                         work_type,
                                         websocket)
        await self.accept_client(client_key, chat_client, websocket)
        logger.debug(
            f'act=accept_client client_key={client_key} client_id={client_id} chat_id={chat_id}')
        try:
            while True:
                try:
                    json_payload_receive = await asyncio.wait_for(websocket.receive_json(),
                                                                  timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    payload = json.loads(json_payload_receive) if json_payload_receive else {}
                except TypeError:
                    payload = json_payload_receive
                # client内部处理自己的业务逻辑
                # TODO zgq：这里可以增加线程池防止阻塞
                await chat_client.handle_message(payload)
        except WebSocketDisconnect as e:
            logger.info('act=rcv_client_disconnect {}', str(e))
        except IgnoreException:
            # client 内部自己关闭了ws链接，并无异常的情况
            pass
        except Exception as e:
            # Handle any exceptions that might occur
            logger.exception(str(e))
            await self.close_client(client_key,
                                    code=status.WS_1011_INTERNAL_ERROR,
                                    reason='后端未知错误类型')
        finally:
            try:
                await self.close_client(client_key,
                                        code=status.WS_1000_NORMAL_CLOSURE,
                                        reason='Client disconnected')
            except Exception as e:
                logger.exception(e)
            self.clear_client(client_key)

    async def handle_websocket(
        self,
        flow_id: str,
        chat_id: str,
        websocket: WebSocket,
        user_id: int,
        gragh_data: dict = None,
    ):
        # 建立连接，并存储映射，兼容不复用ws 场景
        key_list = set([get_cache_key(flow_id, chat_id)])
        await self.connect(flow_id, chat_id, websocket)
        # autogen_pool = ThreadPoolManager(max_workers=1, thread_name_prefix='autogen')
        context_dict = {
            get_cache_key(flow_id, chat_id): {
                'status': 'init',
                'has_file': False,
                'flow_id': flow_id,
                'chat_id': chat_id
            }
        }
        payload = {}
        base_param = {
            'user_id': user_id,
            'flow_id': flow_id,
            'chat_id': chat_id,
            'type': 'end',
            'category': 'system'
        }
        try:
            while True:
                try:
                    json_payload_receive = await asyncio.wait_for(websocket.receive_json(),
                                                                  timeout=2.0)
                except asyncio.TimeoutError:
                    json_payload_receive = ''
                try:
                    payload = json.loads(json_payload_receive) if json_payload_receive else {}
                except TypeError:
                    payload = json_payload_receive

                # websocket multi use
                if payload and 'flow_id' in payload:
                    chat_id = payload.get('chat_id')
                    flow_id = payload.get('flow_id')
                    key = get_cache_key(flow_id, chat_id)
                    if key not in key_list:
                        gragh_data, message = self.preper_reuse_connection(
                            flow_id, chat_id, websocket)
                        context_dict.update({
                            key: {
                                'status': 'init',
                                'has_file': False,
                                'flow_id': flow_id,
                                'chat_id': chat_id
                            }
                        })
                        if message:
                            logger.info('act=new_chat message={}', message)
                            erro_resp = ChatResponse(intermediate_steps=message, **base_param)
                            erro_resp.category = 'error'
                            await self.send_json(flow_id, chat_id, erro_resp, add=False)
                            continue
                        logger.info('act=new_chat_init_success key={}', key)
                        key_list.add(key)
                    if not payload.get('inputs'):
                        continue

                # 判断当前是否是空循环
                process_param = {
                    'autogen_pool': thread_pool,
                    'user_id': user_id,
                    'payload': payload,
                    'graph_data': gragh_data,
                    'context_dict': context_dict
                }
                if payload:
                    await self._process_when_payload(flow_id, chat_id, **process_param)
                else:
                    for v in context_dict.values():
                        if v['status'] != 'init':
                            await self._process_when_payload(v['flow_id'], v['chat_id'],
                                                             **process_param)

                # 处理任务状态
                complete_normal = await thread_pool.as_completed(key_list)
                complete = complete_normal
                # if async_task and async_task.done():
                #     logger.debug(f'async_task_complete result={async_task.result}')
                if complete:
                    for future_key, future in complete:
                        try:
                            future.result()
                            logger.debug('task_complete key={}', future_key)
                        except Exception as e:
                            if isinstance(e, concurrent.futures.CancelledError):
                                continue
                            logger.exception('feature_key={} {}', future_key, e)
                            erro_resp = ChatResponse(**base_param)
                            context = context_dict.get(future_key)
                            if context.get('status') == 'init':
                                erro_resp.intermediate_steps = f'LLM 技能执行错误. error={str(e)}'
                            elif context.get('has_file'):
                                erro_resp.intermediate_steps = f'文档解析失败，点击输入框上传按钮重新上传\n\n{str(e)}'
                            else:
                                erro_resp.intermediate_steps = f'Input data is parsed fail. error={str(e)}'
                            context['status'] = 'init'
                            await self.send_json(context.get('flow_id'), context.get('chat_id'),
                                                 erro_resp)
                            erro_resp.type = 'close'
                            await self.send_json(context.get('flow_id'), context.get('chat_id'),
                                                 erro_resp)
        except WebSocketDisconnect as e:
            logger.info('act=rcv_client_disconnect {}', str(e))
        except Exception as e:
            # Handle any exceptions that might occur
            logger.exception(str(e))
            await self.close_connection(flow_id=flow_id,
                                        chat_id=chat_id,
                                        code=status.WS_1011_INTERNAL_ERROR,
                                        reason='后端未知错误类型',
                                        key_list=key_list)

        finally:
            thread_pool.cancel_task(key_list)  # 将进行中的任务进行cancel
            try:
                await self.close_connection(flow_id=flow_id,
                                            chat_id=chat_id,
                                            code=status.WS_1000_NORMAL_CLOSURE,
                                            reason='Client disconnected',
                                            key_list=key_list)
            except Exception as e:
                logger.exception(e)
            self.disconnect(flow_id, chat_id)

    async def _process_when_payload(self, flow_id: str, chat_id: str,
                                    autogen_pool: ThreadPoolManager, **kwargs):
        """
        Process the incoming message and send the response.
        """
        # set start
        user_id = kwargs.get('user_id')
        graph_data = kwargs.get('graph_data')
        payload = kwargs.get('payload')
        key = get_cache_key(flow_id, chat_id)
        context = kwargs.get('context_dict').get(key)

        status_ = context.get('status')

        if payload and status_ != 'init':
            logger.error('act=input_before_complete payload={} status={}', payload, status_)

        if not payload:
            payload = context.get('payload')
        context['payload'] = payload
        is_begin = bool(status_ == 'init' and 'action' not in payload)
        base_param = {'user_id': user_id, 'flow_id': flow_id, 'chat_id': chat_id}
        start_resp = ChatResponse(type='begin', category='system', **base_param)
        if is_begin:
            await self.send_json(flow_id, chat_id, start_resp)
            # 判断下是否是首次创建会话
            if chat_id:
                res = ChatMessageDao.get_messages_by_chat_id(chat_id=chat_id)
                if len(res) <= 1:  # 说明是新建会话
                    websocket = self.active_connections[key]
                    login_user = UserPayload(**{
                        'user_id': user_id,
                        'user_name': UserDao.get_user(user_id).user_name,
                    })
                    AuditLogService.create_chat_flow(login_user, get_request_ip(websocket),
                                                     flow_id)
        start_resp.type = 'start'

        # should input data
        step_resp = ChatResponse(type='end', category='system', **base_param)
        langchain_obj_key = get_cache_key(flow_id, chat_id)
        if status_ == 'init':
            has_file, graph_data = await self.preper_payload(payload, graph_data,
                                                             langchain_obj_key, flow_id, chat_id,
                                                             start_resp, step_resp)
            status_ = 'init_object'
            context.update({'status': status_})
            context.update({'has_file': has_file})

        # build in thread
        if not self.in_memory_cache.get(langchain_obj_key) and status_ == 'init_object':
            thread_pool.submit(key,
                               self.init_langchain_object_task,
                               flow_id,
                               chat_id,
                               user_id,
                               graph_data,
                               trace_id=chat_id)
            status_ = 'waiting_object'
            context.update({'status': status_})

        # run in thread
        if payload and self.in_memory_cache.get(langchain_obj_key):
            action, over = await self.preper_action(flow_id, chat_id, langchain_obj_key, payload,
                                                    start_resp, step_resp)
            logger.debug(
                f"processing_message message={payload.get('inputs')} action={action} over={over}")
            if not over:
                # task_service: 'TaskService' = get_task_service()
                # async_task = asyncio.create_task(
                #     task_service.launch_task(Handler().dispatch_task, self, client_id,
                #                              chat_id, action, payload, user_id))
                from bisheng_langchain.chains.autogen.auto_gen import AutoGenChain
                from bisheng.chat.handlers import Handler
                params = {
                    'session': self,
                    'client_id': flow_id,
                    'chat_id': chat_id,
                    'action': action,
                    'payload': payload,
                    'user_id': user_id,
                    'trace_id': chat_id
                }
                if isinstance(self.in_memory_cache.get(langchain_obj_key), AutoGenChain):
                    # autogen chain
                    logger.info(f'autogen_submit {langchain_obj_key}')
                    autogen_pool.submit(key,
                                        Handler(stream_queue=self.stream_queue[key]).dispatch_task,
                                        **params)
                else:
                    thread_pool.submit(key,
                                       Handler(stream_queue=self.stream_queue[key]).dispatch_task,
                                       **params)
            status_ = 'init'
            context.update({'status': status_})
            context.update({'payload': {}})  # clean message

    def preper_reuse_connection(self, flow_id: str, chat_id: str, websocket: WebSocket):
        # 设置复用的映射关系
        message = ''
        with session_getter() as session:
            gragh_data = session.get(Flow, flow_id)
            if not gragh_data:
                message = '该技能已被删除'
            if gragh_data.status != 2:
                message = '当前技能未上线，无法直接对话'
        gragh_data = gragh_data.data
        self.reuse_connect(flow_id, chat_id, websocket)
        return gragh_data, message

    async def preper_payload(self, payload, graph_data, langchain_obj_key, client_id, chat_id,
                             start_resp: ChatResponse, step_resp: ChatResponse):
        has_file = False
        has_variable = False
        if 'inputs' in payload and ('data' in payload['inputs']
                                    or 'file_path' in payload['inputs']):
            node_data = payload['inputs'].get('data', '') or [payload['inputs']]
            graph_data = self.refresh_graph_data(graph_data, node_data)
            # 上传文件就重新build，有点粗, 改为只有document loader 需要
            node_loader = False

            for nod in node_data:
                if any('Loader' in x['id'] for x in find_next_node(graph_data, nod['id'])):
                    node_loader = True
                    break
            if node_loader:
                self.set_cache(langchain_obj_key, None)  # rebuild object
            has_file = any(['InputFile' in nd.get('id', '') for nd in node_data])
            has_variable = any(['VariableNode' in nd.get('id', '') for nd in node_data])
        if has_file:
            step_resp.intermediate_steps = '文件上传完成，开始解析'
            await self.send_json(client_id, chat_id, start_resp)
            await self.send_json(client_id, chat_id, step_resp, add=False)
            await self.send_json(client_id, chat_id, start_resp)
            logger.info('input_file start_log')
            await asyncio.sleep(-1)  # 快速的跳过
        elif has_variable:
            await self.send_json(client_id, chat_id, start_resp)
            logger.info('input_variable start_log')
            await asyncio.sleep(-1)  # 快速的跳过
        return has_file, graph_data

    async def preper_action(self, client_id, chat_id, langchain_obj_key, payload,
                            start_resp: ChatResponse, step_resp: ChatResponse):
        langchain_obj = self.in_memory_cache.get(langchain_obj_key)
        batch_question = []
        action = ''
        over = False
        if isinstance(langchain_obj, Report):
            action = 'report'
            step_resp.intermediate_steps = '文件解析完成，开始生成报告'
            await self.send_json(client_id, chat_id, step_resp)
        elif payload.get('action') == 'stop':
            action = 'stop'
        elif 'action' in payload:
            action = 'autogen'
        elif 'clear_history' in payload and payload['clear_history']:
            self.chat_history.empty_history(client_id, chat_id)
            action = 'clear_history'
            over = True
        elif 'data' in payload['inputs'] or 'file_path' in payload['inputs']:
            action = 'auto_file'
            batch_question = self.in_memory_cache.get(langchain_obj_key + '_question')
            payload['inputs']['questions'] = batch_question
            if not batch_question:
                # no question
                file_msg = payload['inputs']
                file_msg.pop('id', '')
                file_msg.pop('data', '')
                file = ChatMessage(flow_id=client_id,
                                   chat_id=chat_id,
                                   is_bot=False,
                                   message=file_msg,
                                   type='end',
                                   user_id=step_resp.user_id)
                self.chat_history.add_message(client_id, chat_id, file)
                step_resp.message = ''
                step_resp.intermediate_steps = '文件解析完成'
                await self.send_json(client_id, chat_id, step_resp)
                start_resp.type = 'close'
                await self.send_json(client_id, chat_id, start_resp)
                over = True
            else:
                step_resp.intermediate_steps = '文件解析完成，开始执行'
                await self.send_json(client_id, chat_id, step_resp, add=False)
        await asyncio.sleep(-1)  # 快速的跳过
        return action, over

    # async def init_langchain_object(self, flow_id, chat_id, user_id, graph_data):
    #     session_id = chat_id
    #     session_service = get_session_service()
    #     if session_id is None:
    #         session_id = session_service.generate_key(session_id=session_id, data_graph=graph_data)
    #     # Load the graph using SessionService
    #     session = await session_service.load_session(session_id, graph_data)
    #     graph, artifacts = session if session else (None, None)
    #     if not graph:
    #         raise ValueError('Graph not found in the session')
    #     built_object = await graph.abuild()
    #     key_node = get_cache_key(flow_id, chat_id)
    #     logger.info(f'init_langchain key={key_node}')
    #     question = []
    #     for node in graph.nodes:
    #         if node.vertex_type == 'InputNode':
    #             question.extend(node.build)
    #     self.set_cache(key_node + '_question', question)
    #     self.set_cache(key_node, built_object)
    #     self.set_cache(key_node + '_artifacts', artifacts)
    #     return built_object

    async def init_langchain_object_task(self, flow_id, chat_id, user_id, graph_data):
        key_node = get_cache_key(flow_id, chat_id)
        logger.info(f'init_langchain build_begin key={key_node}')
        with session_getter() as session:
            db_user = session.get(User, user_id)  # 用来支持节点判断用户权限
        artifacts = {}
        start_time = time.time()
        graph = await build_flow_no_yield(graph_data=graph_data,
                                          artifacts=artifacts,
                                          process_file=True,
                                          flow_id=UUID(flow_id).hex,
                                          chat_id=chat_id,
                                          user_name=db_user.user_name)
        await graph.abuild()
        logger.info(f'init_langchain build_end timecost={time.time() - start_time}')
        question = []
        for node in graph.vertices:
            if node.vertex_type in {'InputNode', 'AudioInputNode', 'FileInputNode'}:
                question_parse = await node.get_result()
                if isinstance(question_parse, list):
                    question.extend(question_parse)
                else:
                    question.append(question_parse)

        self.set_cache(key_node + '_question', question)
        input_nodes = graph.get_input_nodes()
        for node in input_nodes:
            # 只存储chain
            if node.base_type == 'inputOutput' and node.vertex_type != 'Report':
                continue
            self.set_cache(key_node, await node.get_result())
            self.set_cache(key_node + '_artifacts', artifacts)
        return flow_id, chat_id

    def refresh_graph_data(self, graph_data: dict, node_data: List[dict]):
        tweak = process_node_data(node_data)
        """upload file to make flow work"""
        return process_tweaks(graph_data, tweaks=tweak)
