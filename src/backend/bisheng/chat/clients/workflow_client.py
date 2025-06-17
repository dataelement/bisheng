import asyncio
import json
from typing import Dict, Optional

from bisheng.utils import generate_uuid
from fastapi import Request, WebSocket, status
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import ChatResponse
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.chat.clients.base import BaseClient
from bisheng.chat.types import WorkType
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import execute_workflow
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.database.models.message import ChatMessageDao, ChatMessage, ChatMessageType


class WorkflowClient(BaseClient):

    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str,
                 user_id: int, login_user: UserPayload, work_type: WorkType, websocket: WebSocket,
                 **kwargs):
        super().__init__(request, client_key, client_id, chat_id, user_id, login_user, work_type,
                         websocket, **kwargs)

        self.workflow: Optional[RedisCallback] = None
        self.latest_history: Optional[ChatMessage] = None
        self.ws_closed = False

    async def close(self, force_stop=True):
        if not force_stop:
            self.ws_closed = True
        # 非会话模式关闭workflow执行, 会话模式判断是否是用户主动关闭的
        if self.workflow:
            if force_stop or not self.chat_id:
                self.workflow.set_workflow_stop()
        else:
            await self.send_response('processing', 'close', '')

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
            await self.init_workflow(message)
        elif message.get('action') == 'check_status':
            await self.check_status(message)
        elif message.get('action') == 'input':
            await self.handle_user_input(message.get('data'))
        elif message.get('action') == 'stop':
            await self.close(force_stop=True)
            # await self.stop_handle_message(message)
        else:
            logger.warning('not support action: %s', message.get('action'))

    async def init_history(self):
        if not self.chat_id:
            return
        self.latest_history = ChatMessageDao.get_latest_message_by_chatid(self.chat_id)
        if not self.latest_history:
            # 用户点击了新建会话，记录审计日志
            AuditLogService.create_chat_workflow(self.login_user, get_request_ip(self.request), self.client_id)

    async def check_status(self, message: dict, is_init: bool = False) -> (bool, str):
        """
        bool: 表示是否需要重新执行workflow
        """
        # chat ws connection first handle
        workflow_id = message.get('flow_id', self.client_id)
        self.chat_id = message.get('chat_id', '')
        unique_id = generate_uuid()
        if self.chat_id:
            await self.init_history()
            unique_id = f'{self.chat_id}_async_task_id'
        logger.debug(f'init workflow with unique_id: {unique_id}, workflow_id: {workflow_id}, chat_id: {self.chat_id}')
        self.workflow = RedisCallback(unique_id, workflow_id, self.chat_id, str(self.user_id))
        # 判断workflow是否已上线，未上线的话关闭当前websocket链接
        workflow_db = FlowDao.get_flow_by_id(workflow_id)
        if workflow_db.status != FlowStatus.ONLINE.value and self.chat_id:
            self.workflow.set_workflow_stop()
            try:
                await self.send_response('processing', 'close', '')
                await self.websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason='当前工作流未上线，无法直接对话')
            except:
                logger.warning('websocket is closed')
                pass
            self.workflow.clear_workflow_status()
            self.workflow = None
            logger.debug('workflow is offline not support with chat')
            return False, unique_id

        status_info = self.workflow.get_workflow_status()
        if not status_info:
            # 说明上一次运行完成了
            self.workflow = None
            if self.latest_history and not is_init:
                # 让前端终止上一次的运行
                await self.send_response('processing', 'close', '')
            return True, unique_id

        # 每次建立链接，都重新运行workflow
        return True, unique_id

        # 说明会话还在运行中
        if status_info['status'] == WorkflowStatus.INPUT.value and self.latest_history:
            # 如果是等待用户输入状态，需要将上一次的输入消息重新发送给前端
            if self.latest_history.category in [WorkflowEventType.UserInput.value,
                                                WorkflowEventType.OutputWithInput.value,
                                                WorkflowEventType.OutputWithChoose.value]:
                send_message = self.latest_history.to_dict()
                send_message['message'] = json.loads(send_message['message'])
                send_message['message_id'] = send_message.pop('id')
                await self.send_json(send_message)
        elif status_info['status'] in [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value]:
            # 说明workflow已经运行完成, 直接运行新的工作流即可
            return True, unique_id

        await self.send_response('processing', 'begin', '')
        logger.debug('init workflow over, continue run workflow')
        await self.workflow_run()
        return False, unique_id

    async def init_workflow(self, message: dict):
        if self.workflow is not None:
            return
        try:
            workflow_data = message.get('data')
            workflow_id = message.get('flow_id', self.client_id)
            flag, unique_id = await self.check_status(message, is_init=True)
            # 说明workflow在运行中或者已下线
            if not flag:
                return

            # 发起新的workflow
            self.workflow = RedisCallback(unique_id, workflow_id, self.chat_id, str(self.user_id))
            self.workflow.set_workflow_data(workflow_data)
            self.workflow.set_workflow_status(WorkflowStatus.WAITING.value)
            # 发起异步任务
            execute_workflow.delay(unique_id, workflow_id, self.chat_id, str(self.user_id))
            await self.send_response('processing', 'begin', '')
            await self.workflow_run()
        except Exception as e:
            logger.exception('init_workflow_error')
            self.workflow = None
            await self.send_response('error', 'over', {'code': 500, 'message': str(e)})
            return

    async def workflow_run(self):
        workflow_over = False
        while not workflow_over:
            if self.ws_closed:
                break
            workflow_over = await self._workflow_run()
            await asyncio.sleep(0.5)

    async def _workflow_run(self):
        # 需要不断从redis中获取workflow返回的消息
        async for event in self.workflow.get_response_until_break():
            await self.send_json(event)

        if not self.workflow:
            logger.warning('workflow is over by other task')
            return True

        status_info = self.workflow.get_workflow_status()
        if not status_info or status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
        # DONE merge_check
        # if status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            await self.send_response('processing', 'close', '')
            self.workflow.clear_workflow_status()
            self.workflow = None
            return True

        # 说明运行到了待输入状态
        elif status_info['status'] != WorkflowStatus.INPUT.value:
            logger.warning(f'workflow status is unknown: {status_info}')
        return False

    async def handle_user_input(self, data: dict):
        logger.info(f'get user input: {data}')
        if not self.workflow:
            logger.warning('workflow is over')
            return
        status_info = self.workflow.get_workflow_status(user_cache=False)
        if status_info['status'] != WorkflowStatus.INPUT.value:
            logger.warning(f'workflow is not input status: {status_info}')
        else:
            user_input = {}
            message_id = None
            new_message = None
            # 目前只支持一个输入节点
            for node_id, node_info in data.items():
                user_input[node_id] = node_info['data']
                message_id = node_info.get('message_id')
                new_message = node_info.get('message')
                break
            self.workflow.set_user_input(user_input, message_id=message_id, message_content=new_message)
            self.workflow.set_workflow_status(WorkflowStatus.INPUT_OVER.value)
        # await self.workflow_run()
