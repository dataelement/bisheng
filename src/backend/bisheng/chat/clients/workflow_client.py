import asyncio
import json
import time
import uuid
from typing import Dict, Optional

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.utils import get_request_ip
from fastapi import Request, WebSocket
from loguru import logger

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import ChatResponse
from bisheng.chat.clients.base import BaseClient
from bisheng.chat.types import WorkType
from bisheng.database.models.message import ChatMessageDao, ChatMessage, ChatMessageType
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import execute_workflow
from bisheng.workflow.common.workflow import WorkflowStatus


class WorkflowClient(BaseClient):

    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str,
                 user_id: int, login_user: UserPayload, work_type: WorkType, websocket: WebSocket,
                 **kwargs):
        super().__init__(request, client_key, client_id, chat_id, user_id, login_user, work_type,
                         websocket, **kwargs)

        self.workflow: Optional[RedisCallback] = None
        self.latest_history: Optional[ChatMessage] = None

    async def close(self):
        # 非会话模式关闭workflow执行
        if self.workflow and not self.chat_id:
            self.workflow.set_workflow_stop()
        self.workflow = None

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
        elif message.get('action') == 'input':
            await self.handle_user_input(message.get('data'))
        elif message.get('action') == 'stop':
            await self.close()
            await self.stop_handle_message(message)
        else:
            logger.warning('not support action: %s', message.get('action'))

    async def init_history(self):
        if not self.chat_id:
            return
        self.latest_history = ChatMessageDao.get_latest_message_by_chatid(self.chat_id)
        if not self.latest_history:
            # 新建会话，记录审计日志
            AuditLogService.create_chat_workflow(self.login_user, get_request_ip(self.request), self.client_id)

    async def init_workflow(self, message: dict):
        if self.workflow is not None:
            return
        try:
            workflow_data = message.get('data')
            workflow_id = message.get('flow_id', self.client_id)
            # 查询chat_id对应的异步任务唯一标识
            unique_id = uuid.uuid4().hex
            if self.chat_id:
                await self.init_history()
                unique_id = f'{self.chat_id}_async_task_id'
            logger.debug(f'init workflow with unique_id: {unique_id}, workflow_id: {workflow_id}, chat_id: {self.chat_id}')
            self.workflow = RedisCallback(unique_id, workflow_id, self.chat_id, str(self.user_id))
            status_info = self.workflow.get_workflow_status()
            if not status_info:
                if self.latest_history:
                    # 让前端终止上一次的运行
                    await self.send_response('processing', 'close', '')
                # 发起新的workflow
                self.workflow.set_workflow_data(workflow_data)
                self.workflow.set_workflow_status(WorkflowStatus.WAITING.value)
                # 发起异步任务
                execute_workflow.delay(unique_id, workflow_id, self.chat_id, str(self.user_id))
            elif status_info['status'] == WorkflowStatus.INPUT.value and self.latest_history:
                # 如果是等待用户输入状态，需要将上一次的输入消息重新发送给前端
                if self.latest_history.category in ['user_input', 'output_choose_msg', 'output_input_msg']:
                    send_message = self.latest_history.to_dict()
                    send_message['message'] = json.loads(send_message['message'])
                    await self.send_json(send_message)

        except Exception as e:
            logger.exception('init_workflow_error')
            self.workflow = None
            await self.send_response('error', 'over', str(e))
            return
        await self.send_response('processing', 'begin', '')
        logger.debug('init workflow over')
        # 运行workflow
        await self.workflow_run()

    async def workflow_run(self):
        # 需要不断从redis中获取workflow返回的消息
        while True:
            if not self.workflow:
                break
            status_info = self.workflow.get_workflow_status()
            if not status_info:
                await self.send_response('error', 'over', 'workflow status not found')
                await self.send_response('processing', 'close', '')
                return
            elif status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                # 防止有消息未发送，查询下消息队列
                send_msg = True
                while send_msg:
                    chat_response = self.workflow.get_workflow_response()
                    if chat_response:
                        await self.send_json(chat_response)
                    else:
                        send_msg = False

                if status_info['status'] == WorkflowStatus.FAILED.value:
                    await self.send_response('error', 'over', status_info['reason'])
                await self.send_response('processing', 'close', '')
                self.workflow.clear_workflow_status()
                logger.debug('clear workflow status')
                self.workflow = None
                break
            elif time.time() - status_info['time'] > 86400:
                # 保底措施: 如果状态一天未更新，结束workflow，说明异步任务出现问题
                self.workflow.set_workflow_stop()
                await self.send_response('error', 'over', 'workflow status not update over 1 day')
                await self.send_response('processing', 'close', '')
                self.workflow.clear_workflow_status()
                break
            else:
                chat_response = self.workflow.get_workflow_response()
                if not chat_response:
                    await asyncio.sleep(1)
                    continue
                await self.send_json(chat_response)

        logger.debug('workflow run over')

    async def handle_user_input(self, data: dict):
        logger.info(f'get user input: {data}')
        if not self.workflow:
            logger.warning('workflow is over')
            return
        status_info = self.workflow.get_workflow_status(user_cache=False)
        if status_info['status'] != WorkflowStatus.INPUT.value:
            logger.warning('workflow is not input status')
            return
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
        self.workflow.set_user_input(user_input)
