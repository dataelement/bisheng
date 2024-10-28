import json
from abc import abstractmethod, ABC
from typing import Dict, Callable
from uuid import uuid4

from loguru import logger
from fastapi import WebSocket, status, Request

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import IgnoreException, WorkType
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.settings import settings
from bisheng.api.utils import get_request_ip
from bisheng.utils.threadpool import ThreadPoolManager, thread_pool


class BaseClient(ABC):
    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str, user_id: int,
                 login_user: UserPayload, work_type: WorkType, websocket: WebSocket, **kwargs):
        self.request = request
        self.client_key = client_key
        self.client_id = client_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.login_user = login_user
        self.work_type = work_type
        self.websocket = websocket
        self.kwargs = kwargs

        # 异步任务列表
        self.task_ids = []

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage):
        await self.websocket.send_json(message.dict())

    async def handle_message(self, message: Dict[any, any]):
        """ 处理客户端发过来的信息, 提交到线程池内执行 """
        trace_id = uuid4().hex
        logger.info(f'client_id={self.client_key} trace_id={trace_id} message={message}')
        with logger.contextualize(trace_id=trace_id):
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
        # 包装处理函数为异步任务
        self.task_ids.append(task_id)
        try:
            # 执行处理函数
            await fn(*args, **kwargs)
        except Exception as e:
            logger.exception("handle message error")
        finally:
            # 执行完成后将任务id从列表移除
            self.task_ids.remove(task_id)

    async def add_message(self, msg_type: str, message: str, category: str, remark: str = ''):
        """ 保存历史消息到数据库 """
        if not self.chat_id:
            # debug模式无需保存历史
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

    async def send_response(self, category: str, msg_type: str, message: str, intermediate_steps: str = '',
                            message_id: int = None):
        """ 给客户端发送响应消息 """
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
        # 中止消息处理逻辑
        logger.info(f'need stop agent, client_key: {self.client_key}, message: {message}')

        # 中止之前的处理函数 因为最新的任务id是中止任务的id，不能取消自己
        thread_pool.cancel_task(self.task_ids[:-1])

        await self.send_response('processing', 'close', '')
