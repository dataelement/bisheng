import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextvars import ContextVar

from fastapi import Request, WebSocket
from loguru import logger

from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.common.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.logger import trace_id_var
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.utils.threadpool import thread_pool

_message_execution: ContextVar[tuple | None] = ContextVar("chat_message_execution", default=None)


class BaseClient(ABC):
    # F132: set by ChatManager.dispatch_client for logged-in connections only.
    memory_register = None

    @property
    def current_execution_context(self):
        context = _message_execution.get()
        return context[1] if context is not None and context[0] is self else None

    @property
    def user_id(self):
        context = self.current_execution_context
        return context.operator.user_id if context is not None else self._connection_user_id

    @user_id.setter
    def user_id(self, value):
        self._connection_user_id = value

    @property
    def login_user(self):
        context = self.current_execution_context
        return context.operator if context is not None else self._connection_login_user

    @login_user.setter
    def login_user(self, value):
        self._connection_login_user = value

    def __init__(
        self,
        request: Request,
        client_key: str,
        client_id: str,
        chat_id: str,
        user_id: int,
        login_user: UserPayload,
        work_type: WorkType,
        websocket: WebSocket,
        **kwargs,
    ):
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

    async def handle_message(self, message: dict[any, any], *, execution_context=None):
        """Handling messages from clients, Submit to Thread Pool for Execution"""
        trace_id = trace_id_var.get()
        action = message.get("action")
        if action == "agent_interaction_submit":
            logger.info("client_id={} trace_id={} action=agent_interaction_submit", self.client_key, trace_id)
        else:
            logger.info(f"client_id={self.client_key} trace_id={trace_id} message={message}")

        if action in ("stop", "agent_interaction_submit"):
            await self._invoke_message(message, execution_context)
            return
        thread_pool.submit(
            trace_id, self.wrapper_task, trace_id, self._invoke_message, message, execution_context, trace_id=trace_id
        )

    async def _invoke_message(self, message, execution_context):
        # 只覆盖本任务的身份视图。工作流状态仍在原连接对象中。
        token = _message_execution.set((self, execution_context)) if execution_context is not None else None
        try:
            await self._handle_message(message)
        finally:
            if token is not None:
                _message_execution.reset(token)

    @abstractmethod
    async def _handle_message(self, message: dict[any, any]):
        raise Exception("handle_message must be implemented")

    async def wrapper_task(self, task_id: str, fn: Callable, *args, **kwargs):
        logger.debug("wrapper_task task_id=%s", task_id)
        # The wrapper handler function is an asynchronous task
        self.task_ids.append(task_id)
        try:
            # Execute Handling Functions
            await fn(*args, **kwargs)
        except Exception:
            logger.exception("handle message error")
        finally:
            # When the execution is complete, the task will beidRemove from list
            self.task_ids.remove(task_id)

    async def add_message(self, msg_type: str, message: str, category: str, remark: str = ""):
        """Save Historical Messages to Database"""
        if not self.chat_id:
            # debugMode does not need to save history
            return
        is_bot = 0 if msg_type == "human" else 1
        msg = ChatMessageDao.insert_one(
            ChatMessageModel(
                is_bot=is_bot,
                source=0,
                message=message,
                category=category,
                type=msg_type,
                extra=json.dumps({"client_key": self.client_key}, ensure_ascii=False),
                flow_id=self.client_id,
                chat_id=self.chat_id,
                user_id=self.user_id,
                remark=remark,
            )
        )
        return msg

    async def send_response(
        self,
        category: str,
        msg_type: str,
        message: str | dict,
        intermediate_steps: str = "",
        message_id: int = None,
        citations=None,
        citation_registry_items=None,
    ):
        """Send a response message to the client"""
        is_bot = 0 if msg_type == "human" else 1
        if citations is None:
            citations = citation_registry_items
        await self.send_json(
            ChatResponse(
                message_id=message_id,
                category=category,
                type=msg_type,
                is_bot=is_bot,
                message=message,
                user_id=self.user_id,
                flow_id=self.client_id,
                chat_id=self.chat_id,
                extra=json.dumps({"client_key": self.client_key}, ensure_ascii=False),
                intermediate_steps=intermediate_steps,
                citations=citations,
                citation_registry_items=citation_registry_items or citations,
            )
        )

    async def stop_handle_message(self, message: dict[any, any]):
        # Abort message processing logic
        logger.info(f"need stop agent, client_key: {self.client_key}, task_ids: {self.task_ids}")

        # Processing function before abort Because the latest taskidis to abort the task.id, you can't cancel yourself
        thread_pool.cancel_task(self.task_ids)
        logger.info(f"need stop over, client_key: {self.client_key}, task_ids: {self.task_ids}")

        await self.send_response("processing", "close", "")
