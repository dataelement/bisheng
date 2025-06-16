import asyncio
import json
from abc import abstractmethod, ABC
from typing import Dict, Callable
from uuid import uuid4
from queue import Queue, Empty

from bisheng.utils import generate_uuid
from loguru import logger
from fastapi import WebSocket, Request
import asyncio

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import WorkType
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.utils.threadpool import thread_pool


class BaseClient(ABC):
    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str, user_id: int,
                 login_user: UserPayload, work_type: WorkType, websocket: WebSocket, **kwargs):
        self.request = request
        self.client_key = client_key  # 客户端唯一标识
        self.client_id = client_id  # 业务的唯一标识，如助手或者技能ID
        self.chat_id = chat_id
        self.user_id = user_id
        self.login_user = login_user
        self.work_type = work_type
        self.websocket = websocket
        self.kwargs = kwargs

        # 异步任务列表
        self.task_ids = []
        # ws消息队列, 用于存储发送给客户端的websocket消息
        self.ws_msg_queue = Queue()

        # 启动消息消费任务, websocket的消息不能再多个协程中发送，否则会出现异常
        thread_pool.submit(f'websocket_send_json_{self.client_key}', self.consume_message)

    async def close(self):
        pass

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage | dict):
        if isinstance(message, dict):
            self.ws_msg_queue.put(message)
            return
        self.ws_msg_queue.put(message.dict())

    async def consume_message(self):
        while True:
            data = None
            try:
                data = self.ws_msg_queue.get_nowait()
                await self.websocket.send_json(data)
            except Empty:
                pass
            except Exception as e:
                logger.error(f"consume_message error {data} error: {str(e)}")
                break
            await asyncio.sleep(0.01)

    async def handle_message(self, message: Dict[any, any]):
        """ 处理客户端发过来的信息, 提交到线程池内执行 """
        trace_id = generate_uuid()
        logger.info(f'client_id={self.client_key} trace_id={trace_id} message={message}')
        with logger.contextualize(trace_id=trace_id):
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

    async def send_response(self, category: str, msg_type: str, message: str | dict, intermediate_steps: str = '',
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
        logger.info(f'need stop agent, client_key: {self.client_key}, task_ids: {self.task_ids}')

        # 中止之前的处理函数 因为最新的任务id是中止任务的id，不能取消自己
        thread_pool.cancel_task(self.task_ids)
        logger.info(f'need stop over, client_key: {self.client_key}, task_ids: {self.task_ids}')

        await self.send_response('processing', 'close', '')
