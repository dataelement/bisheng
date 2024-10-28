from queue import Queue
from typing import Dict

from fastapi import WebSocket, Request
from loguru import logger

from bisheng.api.services.user_service import UserPayload

from bisheng.chat.clients.base import BaseClient
from bisheng.chat.clients.workflow_callback import WorkflowWsCallback
from bisheng.chat.types import WorkType
from bisheng.workflow.graph.workflow import Workflow


class WorkflowClient(BaseClient):
    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str, user_id: int,
                 login_user: UserPayload, work_type: WorkType, websocket: WebSocket, **kwargs):
        super().__init__(request, client_key, client_id, chat_id, user_id, login_user, work_type, websocket, **kwargs)

        self.workflow = None
        self.input_queue = Queue()
        self.callback = WorkflowWsCallback(websocket=self.websocket,
                                           chat_id=self.chat_id,
                                           workflow_id=self.client_id,
                                           user_id=self.user_id)

    async def _handle_message(self, message: Dict[any, any]):
        logger.debug('----------------------------- start handle message -----------------------')
        if message.get("action") == "init_data":
            # 初始化workflow数据
            await self.init_workflow(message.get("data"))
        elif message.get("action") == "input":
            await self.handle_user_input(message.get("data"))
        else:
            logger.warning("not support action: %s", message.get("action"))

    async def init_workflow(self, workflow_data: dict):
        # todo max_steps and timeout 放到系统配置内
        await self.send_response('processing', 'begin', '')
        self.workflow = Workflow(self.client_id, str(self.user_id), workflow_data,
                                 50, 60, self.callback, self.input_queue)
        logger.debug("init workflow over")
        # 运行workflow
        status, reason = self.workflow.run()
        await self.send_response('processing', 'close', reason)

    async def handle_user_input(self, data):
        self.input_queue.put(data)
