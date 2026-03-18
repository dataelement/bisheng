import asyncio
import json
import time
from collections import defaultdict
from queue import Queue
from typing import Any, Dict, List

from fastapi import Request, WebSocket, WebSocketDisconnect, status
from loguru import logger

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schemas import ChatMessage, ChatResponse, FileResponse
from bisheng.chat.client import ChatClient
from bisheng.chat.clients.workflow_client import WorkflowClient
from bisheng.chat.types import IgnoreException, WorkType
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData
from bisheng.common.services import telemetry_service
from bisheng.core.cache.flow import InMemoryCache
from bisheng.core.cache.manager import Subject, cache_manager
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.utils import generate_uuid
from bisheng.utils.util import get_cache_key


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
        db_message = None
        if chat_id and (message.message or message.intermediate_steps
                        or message.files) and message.type != 'stream':
            msg = message.copy()
            msg.message = json.dumps(msg.message, ensure_ascii=False) if isinstance(msg.message, dict) else msg.message
            files = json.dumps(msg.files) if msg.files else ''
            msg.__dict__.pop('files')
            db_message = ChatMessage(files=files, **msg.__dict__)
            logger.info(f'chat={db_message} time={time.time() - t1}')
            with get_sync_db_session() as seesion:
                seesion.add(db_message)
                seesion.commit()
                seesion.refresh(db_message)
                message.message_id = db_message.id

        if not isinstance(message, FileResponse):
            self.notify()
        return db_message

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
        # Connected clients
        self.active_clients: Dict[str, ChatClient] = {}

        # Record Streaming Output Results
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
        # Add message thread
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
        if websocket := self.active_connections.get(get_cache_key(flow_id, chat_id)):
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
                self.clear_client(client_key)
                await chat_client.close()
                await chat_client.websocket.close(code=code, reason=reason)
            except RuntimeError as exc:
                # This is to catch the following error:
                #  Unexpected ASGI message 'websocket.close', after sending 'websocket.close'
                if 'after sending' in str(exc):
                    logger.error(exc)

    async def dispatch_client(
            self,
            request: Request | WebSocket,  # Raw request body
            client_id: str,
            chat_id: str,
            login_user: UserPayload,
            work_type: WorkType,
            websocket: WebSocket,
            graph_data: dict = None):
        start_time = time.time()
        client_key = generate_uuid()
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
                # clientHandle your own business logic internally
                # TODO zgq: Here you can increase the thread pool to prevent blocking
                await chat_client.handle_message(payload)
        except WebSocketDisconnect as e:
            logger.info('act=rcv_client_disconnect {}', str(e))
        except IgnoreException:
            # client Inside closed on its ownwsLink, no abnormalities
            pass
        except Exception as e:
            # Handle any exceptions that might occur
            logger.exception(str(e))
            await self.close_client(client_key,
                                    code=status.WS_1011_INTERNAL_ERROR,
                                    reason='Backend Unknown Error Type')
        finally:
            try:
                await self.close_client(client_key,
                                        code=status.WS_1000_NORMAL_CLOSURE,
                                        reason='Client disconnected')
            except Exception as e:
                logger.exception(e)
            self.clear_client(client_key)
            if work_type == WorkType.GPTS:
                app_info = await AssistantService.get_one_assistant(client_id)
                app_type = ApplicationTypeEnum.ASSISTANT
            else:
                app_info = await WorkFlowService.get_one_workflow_simple_info(client_id)
                app_type = ApplicationTypeEnum.WORKFLOW
            app_name = app_info.name if app_info else 'unknown'
            await telemetry_service.log_event(user_id=login_user.user_id,
                                              event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                              trace_id=trace_id_var.get(),
                                              event_data=ApplicationAliveEventData(
                                                  app_id=client_id,
                                                  app_name=app_name,
                                                  app_type=app_type,
                                                  chat_id=chat_id,
                                                  start_time=int(start_time),
                                                  end_time=int(time.time()),
                                              ))
