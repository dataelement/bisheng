import asyncio
import json
import uuid
from typing import Dict, Optional

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

    async def close(self):
        if self.workflow:
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

    async def handle_message(self, message: Dict[any, any]):
        """ 处理客户端发过来的信息, 提交到线程池内执行 """
        trace_id = uuid.uuid4().hex
        logger.info(f'client_id={self.client_key} trace_id={trace_id} message={message}')
        with logger.contextualize(trace_id=trace_id):
            await self._handle_message(message)

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

    async def init_workflow(self, message: dict):
        if self.workflow is not None:
            return
        try:
            workflow_data = message.get('data')
            workflow_id = message.get('flow_id', self.client_id)
            # 查询chat_id对应的异步任务唯一标识
            unique_id = uuid.uuid4().hex
            if self.chat_id:
                unique_id = f'{self.chat_id}_async_task_id'
            logger.debug(f'init workflow with unique_id: {unique_id}, workflow_id: {workflow_id}, chat_id: {self.chat_id}')
            self.workflow = RedisCallback(unique_id, workflow_id, self.chat_id, str(self.user_id))
            status_info = self.workflow.get_workflow_status()
            if not status_info:
                self.workflow.set_workflow_data(workflow_data)
                self.workflow.set_workflow_status(WorkflowStatus.WAITING.value)
                # 发起异步任务
                execute_workflow.delay(unique_id, workflow_id, self.chat_id, str(self.user_id))
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
        status_info = self.workflow.get_workflow_status()
        if status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            self.workflow = None
            if status_info['status'] == WorkflowStatus.FAILED.value:
                await self.send_response('error', 'over', status_info['reason'])
            await self.send_response('processing', 'close', '')
            return status_info
        # 需要不断从redis中获取workflow返回的消息
        while True:
            if not self.workflow:
                break
            status_info = self.workflow.get_workflow_status()
            if status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                # 防止有消息未发送，查询下消息队列
                send_msg = True
                while send_msg:
                    chat_response = self.workflow.get_workflow_response()
                    if chat_response:
                        await self.send_json(chat_response)
                    else:
                        send_msg = False

                self.workflow = None
                if status_info['status'] == WorkflowStatus.FAILED.value:
                    await self.send_response('error', 'over', status_info['reason'])
                await self.send_response('processing', 'close', '')
                break
            else:
                chat_response = self.workflow.get_workflow_response()
                if not chat_response:
                    await asyncio.sleep(1)
                    continue
                await self.send_json(chat_response)


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
