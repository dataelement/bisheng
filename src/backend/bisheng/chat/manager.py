import asyncio
import json
from collections import defaultdict
from email.utils import unquote
from typing import Any, Dict, List
from urllib.parse import urlparse
from uuid import UUID

from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import ChatMessage, ChatResponse, FileResponse
from bisheng.cache import cache_manager
from bisheng.cache.flow import InMemoryCache
from bisheng.cache.manager import Subject
from bisheng.database.base import get_session
from bisheng.database.models.user import User
from bisheng.processing.process import process_tweaks
from bisheng.utils.logger import logger
from bisheng.utils.threadpool import ThreadPoolManager
from bisheng.utils.util import get_cache_key
from bisheng_langchain.input_output.output import Report
from fastapi import WebSocket


class ChatHistory(Subject):

    def __init__(self):
        super().__init__()
        self.history: Dict[str, List[ChatMessage]] = defaultdict(list)

    def add_message(self, client_id: str, chat_id: str, message: ChatMessage):
        """Add a message to the chat history."""

        if chat_id and (message.message or message.intermediate_steps
                        or message.files) and message.type != 'stream':
            with next(get_session()) as seesion:
                from bisheng.database.models.message import ChatMessage
                msg = message.copy()
                msg.message = str(msg.message) if isinstance(msg.message, dict) else msg.message
                files = json.dumps(msg.files) if msg.files else ''
                msg.__dict__.pop('files')
                db_message = ChatMessage(flow_id=client_id,
                                         chat_id=chat_id,
                                         files=files,
                                         **msg.__dict__)
                logger.info(f'chat={db_message}')
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

    # def on_chat_history_update(self):
    #     """Send the last chat message to the client."""
    #     client_id = self.cache_manager.current_client_id
    #     if client_id in self.active_connections:
    #         chat_response = self.chat_history.get_history(client_id, filter_messages=False)[-1]
    #         if chat_response.is_bot:
    #             # Process FileResponse
    #             if isinstance(chat_response, FileResponse):
    #                 # If data_type is pandas, convert to csv
    #                 if chat_response.data_type == 'pandas':
    #                     chat_response.data = chat_response.data.to_csv()
    #                 elif chat_response.data_type == 'image':
    #                     # Base64 encode the image
    #                     chat_response.data = pil_to_base64(chat_response.data)
    #             # get event loop
    #             loop = asyncio.get_event_loop()

    #             coroutine = self.send_json(client_id, chat_response)
    #             asyncio.run_coroutine_threadsafe(coroutine, loop)

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

    def disconnect(self, client_id: str, chat_id: str):
        self.active_connections.pop(get_cache_key(client_id, chat_id), None)

    async def send_message(self, client_id: str, chat_id: str, message: str):
        websocket = self.active_connections[get_cache_key(client_id, chat_id)]
        await websocket.send_text(message)

    async def send_json(self, client_id: str, chat_id: str, message: ChatMessage, add=True):
        websocket = self.active_connections[get_cache_key(client_id, chat_id)]
        # 增加消息记录
        if add:
            self.chat_history.add_message(client_id, chat_id, message)
        await websocket.send_json(message.dict())

    async def close_connection(self, client_id: str, chat_id: str, code: int, reason: str):
        if websocket := self.active_connections[get_cache_key(client_id, chat_id)]:
            try:
                await websocket.close(code=code, reason=reason)
                self.disconnect(client_id, chat_id)
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

    async def handle_websocket(
        self,
        client_id: str,
        chat_id: str,
        websocket: WebSocket,
        user_id: int,
        gragh_data: dict = None,
    ):
        await self.connect(client_id, chat_id, websocket)
        thread_pool_local = ThreadPoolManager(max_workers=2)
        status = 'init'  # 创建锁
        payload = {}
        try:
            while True:
                try:
                    json_payload_receive = await asyncio.wait_for(websocket.receive_json(),
                                                                  timeout=2.0)
                except asyncio.TimeoutError:
                    json_payload_receive = ''
                    pass
                try:
                    payload = json.loads(json_payload_receive) if json_payload_receive else payload
                except TypeError:
                    payload = json_payload_receive

                if 'clear_history' in payload:
                    self.chat_history.history[client_id] = []
                    continue
                if 'clear_cache' in payload:
                    self.in_memory_cache

                # set start
                from bisheng.chat.handlers import Handler
                is_begin = True if payload else False
                action = None
                if 'action' in payload:
                    # autogen continue last session,
                    action, is_begin = 'autogen', False

                start_resp = ChatResponse(type='begin', category='system', user_id=user_id)
                step_resp = ChatResponse(type='end', category='system', user_id=user_id)
                if is_begin:
                    await self.send_json(client_id, chat_id, start_resp)
                start_resp.type = 'start'

                # should input data
                langchain_obj_key = get_cache_key(client_id, chat_id)
                if payload and status == 'init':
                    has_file, graph_data = await self.preper_payload(payload, gragh_data,
                                                                     langchain_obj_key, client_id,
                                                                     chat_id, start_resp, step_resp)
                    status = 'init_object'

                # build in thread
                if payload and not self.in_memory_cache.get(
                        langchain_obj_key) and status == 'init_object':
                    thread_pool_local.submit(self.init_langchain_object, client_id, chat_id,
                                             user_id, graph_data)
                    status = 'waiting_object'

                # run in thread
                if payload and self.in_memory_cache.get(langchain_obj_key):
                    logger.info(f"processing_message message={payload['inputs']}")
                    action = await self.preper_action(client_id, chat_id, langchain_obj_key,
                                                      payload, start_resp, step_resp)
                    thread_pool_local.submit(Handler().dispatch_task, self, client_id, chat_id,
                                             action, payload, user_id)
                    status = 'init'
                    payload = {}  # clean message

                # 处理任务状态
                complete = thread_pool_local.as_completed()
                if complete:
                    for future in complete:
                        try:
                            result = future.result()
                            logger.debug(f'task_complete result={result}')
                        except Exception as e:
                            logger.exception(e)
                            step_resp.intermediate_steps = f'Input data is parsed fail. error={str(e)}'
                            if has_file:
                                step_resp.intermediate_steps = f'File is parsed fail. error={str(e)}'
                            await self.send_json(client_id, chat_id, step_resp)
                            start_resp.type = 'close'
                            await self.send_json(client_id, chat_id, start_resp)
                            # socket close?
                            return
        except Exception as e:
            # Handle any exceptions that might occur
            logger.error()
            await self.close_connection(
                client_id=client_id,
                chat_id=chat_id,
                code=status.WS_1011_INTERNAL_ERROR,
                reason=str(e)[:120],
            )
        finally:
            try:
                await self.close_connection(client_id=client_id,
                                            chat_id=chat_id,
                                            code=status.WS_1000_NORMAL_CLOSURE,
                                            reason='Client disconnected')
            except Exception as e:
                logger.error(e)
            self.disconnect(client_id, chat_id)

    async def preper_payload(self, payload, graph_data, langchain_obj_key, client_id, chat_id,
                             start_resp: ChatResponse, step_resp: ChatResponse):
        has_file = False
        if 'inputs' in payload and ('data' in payload['inputs']
                                    or 'file_path' in payload['inputs']):
            node_data = payload['inputs'].get('data', '') or [payload['inputs']]
            graph_data = self.refresh_graph_data(graph_data, node_data)
            self.set_cache(langchain_obj_key, None)  # rebuild object
            has_file = any(['InputFile' in nd.get('id') for nd in node_data])
        if has_file:
            step_resp.intermediate_steps = 'File upload complete and begin to parse'
            await self.send_json(client_id, chat_id, start_resp)
            await self.send_json(client_id, chat_id, step_resp, add=False)
            await self.send_json(client_id, chat_id, start_resp)
            logger.info('input_file start_log')
            await asyncio.sleep(1)  # why frontend not recieve imediately
        return has_file, graph_data

    async def preper_action(self, client_id, chat_id, langchain_obj_key, payload,
                            start_resp: ChatResponse, step_resp: ChatResponse):
        langchain_obj = self.in_memory_cache.get(langchain_obj_key)
        batch_question = []
        action = ''
        if isinstance(langchain_obj, Report):
            action = 'report'
        elif 'data' in payload['inputs'] or 'file_path' in payload['inputs']:
            action = 'auto_file'
            batch_question = self.in_memory_cache.get(langchain_obj_key + '_question')
            payload['inputs']['questions'] = batch_question
            if not batch_question:
                # no question
                step_resp.intermediate_steps = 'File parsing complete'
                await self.send_json(client_id, chat_id, step_resp)
                start_resp.type = 'close'
                await self.send_json(client_id, chat_id, start_resp)
            else:
                step_resp.intermediate_steps = 'File parsing complete. Analysis starting'
                await self.send_json(client_id, chat_id, step_resp, add=False)
        return action

    def init_langchain_object(self, flow_id, chat_id, user_id, graph_data):
        key_node = get_cache_key(flow_id, chat_id)
        logger.info(f'init_langchain key={key_node}')
        session = next(get_session())
        db_user = session.get(User, user_id)  # 用来支持节点判断用户权限
        artifacts = {}
        graph = build_flow_no_yield(graph_data=graph_data,
                                    artifacts=artifacts,
                                    process_file=True,
                                    flow_id=UUID(flow_id).hex,
                                    chat_id=chat_id,
                                    user_name=db_user.user_name)
        langchain_object = graph.build()
        question = []
        [
            question.extend(node._built_object) for node in graph.nodes
            if node.vertex_type == 'InputNode'
        ]

        self.set_cache(key_node + '_question', question)
        for node in langchain_object:
            # 只存储chain
            if node.base_type == 'inputOutput' and node.vertex_type != 'Report':
                continue
            self.set_cache(key_node, node._built_object)
            self.set_cache(key_node + '_artifacts', artifacts)
        return graph

    def refresh_graph_data(self, graph_data: dict, node_data: List[dict]):
        tweak = {}
        for nd in node_data:
            if nd.get('id') not in tweak:
                tweak[nd.get('id')] = {}
            if 'InputFile' in nd.get('id'):
                file_path = nd.get('file_path')
                url_path = urlparse(file_path)
                if url_path.netloc:
                    file_name = unquote(url_path.path.split('/')[-1])
                else:
                    file_name = file_path.split('_', 1)[1] if '_' in file_path else ''
                nd['value'] = file_name
                tweak[nd.get('id')] = {'file_path': file_path, 'value': file_name}
            elif 'VariableNode' in nd.get('id'):
                variables = nd.get('name')
                variable_value = nd.get('value')
                # key
                variables_list = tweak[nd.get('id')].get('variables', [])
                if not variables_list:
                    tweak[nd.get('id')]['variables'] = variables_list
                    tweak[nd.get('id')]['variable_value'] = []
                variables_list.append(variables)
                # value
                variables_value_list = tweak[nd.get('id')].get('variable_value', [])
                variables_value_list.append(variable_value)
        """upload file to make flow work"""
        return process_tweaks(graph_data, tweaks=tweak)
