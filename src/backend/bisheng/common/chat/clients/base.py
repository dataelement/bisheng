import json
from abc import ABC, abstractmethod
from collections.abc import Callable

from fastapi import Request, WebSocket
from loguru import logger

from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.common.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.logger import trace_id_var
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.utils.threadpool import thread_pool


class BaseClient(ABC):
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
        # Department concurrency lease held by this connection (execution lease
        # only — a page lease belongs to the browser tab and is never stored).
        self.execution_lease = None
        self.execution_renew_task = None

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

    async def handle_message(self, message: dict[any, any]):
        """Handling messages from clients, Submit to Thread Pool for Execution"""
        trace_id = trace_id_var.get()
        logger.info(f"client_id={self.client_key} trace_id={trace_id} message={message}")

        if message.get("action") == "stop":
            await self._handle_message(message)
            return
        thread_pool.submit(trace_id, self.wrapper_task, trace_id, self._handle_message, message, trace_id=trace_id)

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


async def ensure_client_execution_lease(client) -> str:
    """Ensure this WebSocket connection occupies a department slot.

    A ``flow_lease_id`` query parameter means the browser page already holds the
    lease and renews it by heartbeat: this connection only re-asserts it and
    never releases it. Without one, the connection takes its own execution lease
    on first execution and keeps it until the connection closes.

    Returns the outcome value (``held`` / ``rejected`` / ``skipped``) so callers
    can branch without importing the enum themselves.
    """
    # Imported lazily: this module sits on the common import path and the
    # department service pulls in the department DAOs.
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
        normalize_lease_id,
    )

    page_lease_id = normalize_lease_id(client.kwargs.get("flow_lease_id"))
    if page_lease_id is not None:
        outcome, _ = await DepartmentFlowService.ensure_lease(client.login_user, page_lease_id)
        return outcome.value

    if client.execution_lease is not None:
        # Later executions on the same connection reuse the lease already held.
        return SlotOutcome.HELD.value

    outcome, lease = await DepartmentFlowService.ensure_lease(client.login_user)
    if outcome is SlotOutcome.HELD and lease is not None:
        client.execution_lease = lease
        client.execution_renew_task = DepartmentFlowService.start_renewal(lease)
    return outcome.value


async def release_client_execution_lease(client) -> None:
    """Cancel renewal, then release this connection's execution lease.

    Called from ``dispatch_client``'s ``finally`` so it runs however the
    connection ends. A page lease is never stored here, so nothing is released
    for it.
    """
    lease = getattr(client, "execution_lease", None)
    task = getattr(client, "execution_renew_task", None)
    if lease is None and task is None:
        return
    from bisheng.department.domain.services.department_flow_service import DepartmentFlowService

    client.execution_lease = None
    client.execution_renew_task = None
    await DepartmentFlowService.stop_renewal(task, lease)
