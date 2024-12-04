import json
from typing import Dict

from fastapi import Request, WebSocket
from loguru import logger

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import ChatResponse
from bisheng.chat.clients.base import BaseClient
from bisheng.chat.clients.workflow_callback import WorkflowWsCallback
from bisheng.chat.types import WorkType
from bisheng.database.models.message import ChatMessageDao, ChatMessage, ChatMessageType
from bisheng.settings import settings
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.workflow import Workflow


class WorkflowClient(BaseClient):

    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str,
                 user_id: int, login_user: UserPayload, work_type: WorkType, websocket: WebSocket,
                 **kwargs):
        super().__init__(request, client_key, client_id, chat_id, user_id, login_user, work_type,
                         websocket, **kwargs)

        self.workflow = None
        self.callback = WorkflowWsCallback(websocket=self.websocket,
                                           chat_id=self.chat_id,
                                           workflow_id=self.client_id,
                                           user_id=self.user_id)

    async def save_chat_message(self, chat_response: ChatResponse) -> int | None:
        if not self.chat_id:
            return

        message = ChatMessageDao.insert_one(ChatMessage(**{
            'user_id': self.user_id,
            'chat_id': self.chat_id,
            'flow_id': self.client_id,
            'type': ChatMessageType.WORKFLOW.value,

            'is_bot': chat_response.is_bot,
            'source': chat_response.source,
            'message': chat_response.message if isinstance(chat_response.message, str) else json.dumps(
                chat_response.message, ensure_ascii=False
            ),
            'extra': chat_response.extra,
            'category': chat_response.category,
        }))
        return message.id

    async def update_chat_message(self, message_id: int, message: dict | str):
        db_message = ChatMessageDao.get_message_by_id(message_id)
        if db_message:
            db_message.message = message if isinstance(message, str) else json.dumps(message)
            ChatMessageDao.update_message_model(db_message)

    async def _handle_message(self, message: Dict[any, any]):
        logger.debug('----------------------------- start handle message -----------------------')
        if message.get('action') == 'init_data':
            # 初始化workflow数据
            await self.init_workflow(message.get('data'))
        elif message.get('action') == 'input':
            await self.handle_user_input(message.get('data'))
        elif message.get('action') == 'stop':
            await self.stop_handle_message(message)
        else:
            logger.warning('not support action: %s', message.get('action'))

    async def init_workflow(self, workflow_data: dict):
        if self.workflow is not None:
            return
        workflow_conf = settings.get_workflow_conf()
        try:
            self.workflow = Workflow(self.client_id, str(self.user_id), workflow_data, workflow_conf.max_steps,
                                     workflow_conf.timeout,
                                     self.callback)
        except Exception as e:
            logger.exception('init_workflow_error')
            self.workflow = None
            await self.send_response('error', 'over', str(e))
            return
        await self.send_response('processing', 'begin', '')
        logger.debug('init workflow over')
        # 运行workflow
        await self.workflow_run()

    async def workflow_run(self, input_data: dict = None):
        status, reason = self.workflow.run(input_data)
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            self.workflow = None
            if status == WorkflowStatus.FAILED.value:
                await self.send_response('error', 'over', reason)
            await self.send_response('processing', 'close', '')
        # 否则就是需要用户输入

    async def handle_user_input(self, data: dict):
        logger.info(f'get user input: {data}')

        user_input = {}
        for node_id, node_info in data.items():
            user_input[node_id] = node_info['data']
            # 保存用户输入到历史记录
            if node_info.get('message_id'):
                # 更新聊天消息
                await self.update_chat_message(node_info['message_id'], node_info['message'])
            else:
                # 插入新的聊天消息
                await self.save_chat_message(ChatResponse(message=node_info['message'],
                                                          category='question',
                                                          is_bot=False,
                                                          type='end',
                                                          flow_id=self.client_id,
                                                          chat_id=self.chat_id,
                                                          user_id=self.user_id))
        if not self.workflow:
            logger.warning('workflow is over')
            return
        if self.workflow.graph_engine.status != WorkflowStatus.INPUT.value:
            logger.warning('workflow is not in input status')
            return
        await self.workflow_run(user_input)
