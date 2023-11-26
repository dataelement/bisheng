import asyncio
import json
from collections import defaultdict
from typing import Any, Dict, List
from uuid import UUID

from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import ChatMessage, ChatResponse, FileResponse
from bisheng.cache import cache_manager
from bisheng.cache.flow import InMemoryCache
from bisheng.cache.manager import Subject
from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow
from bisheng.processing.process import process_tweaks
from bisheng.utils.logger import logger
from bisheng.utils.util import get_cache_key
from fastapi import WebSocket, status


class ChatHistory(Subject):

    def __init__(self):
        super().__init__()
        self.history: Dict[str, List[ChatMessage]] = defaultdict(list)

    def add_message(self, client_id: str, chat_id: str, message: ChatMessage):
        """Add a message to the chat history."""

        if chat_id and (message.message or message.intermediate_steps or
                        message.files) and message.type != 'stream':
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

    async def handle_websocket(self, client_id: str, chat_id: str,
                               websocket: WebSocket, user_id: int):
        await self.connect(client_id, chat_id, websocket)

        try:
            while True:
                json_payload = await websocket.receive_json()
                try:
                    payload = json.loads(json_payload)
                except TypeError:
                    payload = json_payload
                if 'clear_history' in payload:
                    self.chat_history.history[client_id] = []
                    continue

                if 'clear_cache' in payload:
                    self.in_memory_cache

                # set start
                action = 'default'
                from bisheng.chat.handlers import Handler
                is_begin = True
                if 'action' in payload:
                    # autogen continue last session,
                    is_begin = False
                    action = 'autogen'
                    asyncio.create_task(Handler().dispatch_task(self, client_id,
                                                                chat_id, action,
                                                                payload, user_id))
                if is_begin:
                    start_resp = ChatResponse(type='begin', category='system', user_id=user_id)
                    await self.send_json(client_id, chat_id, start_resp)
                    start_resp.type = 'start'
                    await self.send_json(client_id, chat_id, start_resp)

                # should input data
                if 'inputs' in payload and 'data' in payload['inputs']:
                    node_data = payload['inputs']['data']
                    tweak = {}
                    for nd in node_data:
                        if nd.get('id') not in tweak:
                            tweak[nd.get('id')] = {}
                        if 'InputFile' in nd.get('id'):
                            file_path, file_name = nd.get('value').split('_', 1)
                            tweak[nd.get('id')] = {'file_path': file_path, 'value': file_name}
                        else:
                            tweak[nd.get('id')].update({nd.get('name'): nd.get('value')})

                    """upload file to make flow work"""
                    db_flow = next(get_session()).get(Flow, client_id)
                    graph_data = process_tweaks(db_flow.data, tweaks=tweak)

                    # build to activate node
                    artifacts = {}
                    try:
                        graph = build_flow_no_yield(graph_data, artifacts, True,
                                                    UUID(client_id).hex, chat_id)
                    except Exception as e:
                        logger.exception(e)
                        step_resp = ChatResponse(type='end',
                                                 intermediate_steps='File is parsed fail',
                                                 category='system', user_id=user_id)
                        await self.send_json(client_id, chat_id, step_resp)
                        start_resp.type = 'close'
                        await self.send_json(client_id, chat_id, start_resp)
                        # socket close?
                        return

                    # 更新langchainObject
                    langchain_object = graph.build()
                    batch_question = {}
                    for node in langchain_object:
                        key_node = get_cache_key(client_id, chat_id, node.id)
                        self.set_cache(key_node, node._built_object)
                        self.set_cache(key_node + '_artifacts', artifacts)
                        if node.base_type != 'inputOutput':
                            self.set_cache(get_cache_key(client_id, chat_id), node._built_object)
                            if node.vetext_type == 'Report':
                                action = 'report'
                            else:
                                action = 'auto_file'
                        else:
                            batch_question = node._built_object
                if action == 'auto_file':
                    payload['inputs']['questions'] = batch_question
                asyncio.create_task(Handler().dispatch_task(self, client_id, chat_id, action,
                                                            payload, user_id))

        except Exception as e:
            # Handle any exceptions that might occur
            logger.exception(e)
            await self.close_connection(
                client_id=client_id,
                chat_id=chat_id,
                code=status.WS_1011_INTERNAL_ERROR,
                reason=str(e)[:120],
            )
        finally:
            try:
                await self.close_connection(
                    client_id=client_id,
                    chat_id=chat_id,
                    code=status.WS_1000_NORMAL_CLOSURE,
                    reason='Client disconnected',
                )
            except Exception as e:
                logger.error(e)
            self.disconnect(client_id, chat_id)
