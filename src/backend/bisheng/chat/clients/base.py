import json
from abc import abstractmethod, ABC
from typing import Dict, Callable

from fastapi import WebSocket, Request
from loguru import logger

from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.logger import trace_id_var
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.utils import generate_uuid
from bisheng.utils.threadpool import thread_pool


class BaseClient(ABC):
    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str, user_id: int,
                 login_user: UserPayload, work_type: WorkType, websocket: WebSocket, **kwargs):
        self.request = request
        self.client_key = client_key  # Client Unique Identity
        self.client_id = client_id  # Unique identification of the business, such as assistants or skillsID
        self.chat_id = chat_id
        self.user_id = user_id
        self.login_user = login_user
        self.work_type = work_type
        self.websocket = websocket
        self.kwargs = kwargs

        # Asynchronous Task List
        self.task_ids = []
        # wsMessage Queues, Used to store thewebsocketMessages sent by the client

    async def close(self):
        pass

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage | dict):
        if isinstance(message, dict):
            await self.websocket.send_json(message)
            return
        await self.websocket.send_json(message.model_dump())

    async def handle_message(self, message: Dict[any, any]):
        """ Handling messages from clients, Submit to Thread Pool for Execution """
        trace_id = trace_id_var.get()
        logger.info(f'client_id={self.client_key} trace_id={trace_id} message={message}')

        if message.get('action') == 'stop':
            await self._handle_message(message)
            return
        thread_pool.submit(trace_id,
                           self.wrapper_task,
                           trace_id,
                           self._handle_message,
                           message,
                           trace_id=trace_id)

    @abstractmethod
    async def _handle_message(self, message: Dict[any, any]):
        raise Exception('handle_message must be implemented')

    async def wrapper_task(self, task_id: str, fn: Callable, *args, **kwargs):
        logger.debug("wrapper_task task_id=%s", task_id)
        # The wrapper handler function is an asynchronous task
        self.task_ids.append(task_id)
        try:
            # Execute Handling Functions
            await fn(*args, **kwargs)
        except Exception as e:
            logger.exception("handle message error")
        finally:
            # When the execution is complete, the task will beidRemove from list
            self.task_ids.remove(task_id)

    async def add_message(self, msg_type: str, message: str, category: str, remark: str = ''):
        """ Save Historical Messages to Database """
        if not self.chat_id:
            # debugMode does not need to save history
            return
        is_bot = 0 if msg_type == 'human' else 1
        msg = ChatMessageDao.insert_one(ChatMessageModel(
            is_bot=is_bot,
            source=0,
            message=message,
            category=category,
            type=msg_type,
            extra=json.dumps({'client_key': self.client_key}, ensure_ascii=False),
            flow_id=self.client_id,
            chat_id=self.chat_id,
            user_id=self.user_id,
            remark=remark,
        ))
        return msg

    async def send_response(self, category: str, msg_type: str, message: str | dict, intermediate_steps: str = '',
                            message_id: int = None):
        """ Send a response message to the client """
        is_bot = 0 if msg_type == 'human' else 1
        await self.send_json(ChatResponse(
            message_id=message_id,
            category=category,
            type=msg_type,
            is_bot=is_bot,
            message=message,
            user_id=self.user_id,
            flow_id=self.client_id,
            chat_id=self.chat_id,
            extra=json.dumps({'client_key': self.client_key}, ensure_ascii=False),
            intermediate_steps=intermediate_steps,
        ))

    async def stop_handle_message(self, message: Dict[any, any]):
        # Abort message processing logic
        logger.info(f'need stop agent, client_key: {self.client_key}, task_ids: {self.task_ids}')

        # Processing function before abort Because the latest taskidis to abort the task.id, you can't cancel yourself
        thread_pool.cancel_task(self.task_ids)
        logger.info(f'need stop over, client_key: {self.client_key}, task_ids: {self.task_ids}')

        await self.send_response('processing', 'close', '')
