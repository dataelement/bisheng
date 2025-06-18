import asyncio
import json
import os
import time
import uuid
from typing import AsyncIterator

from cachetools import TTLCache
from langchain_core.documents import Document
from loguru import logger

from bisheng.api.errcode.flow import WorkFlowNodeRunMaxTimesError, WorkFlowWaitUserTimeoutError, \
    WorkFlowNodeUpdateError, WorkFlowVersionUpdateError, WorkFlowTaskBusyError
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import ChatResponse
from bisheng.cache.redis import redis_client
from bisheng.chat.utils import sync_judge_source, sync_process_source_document
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessageDao, ChatMessage, ChatMessageType
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.settings import settings
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import NodeStartData, NodeEndData, UserInputData, GuideWordData, GuideQuestionData, \
    OutputMsgData, StreamMsgData, StreamMsgOverData, OutputMsgChooseData, OutputMsgInputData
from bisheng.workflow.common.workflow import WorkflowStatus



class RedisCallback(BaseCallback):

    def __init__(self, unique_id: str, workflow_id: str, chat_id: str, user_id: str):
        super(RedisCallback, self).__init__()
        # 异步任务的唯一ID
        self.unique_id = unique_id
        self.workflow_id = workflow_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.workflow = None
        self.create_session = False

        # workflow status cache in memory 10 seconds
        self.workflow_cache: TTLCache = TTLCache(maxsize=1024, ttl=10)

        self.redis_client = redis_client
        self.workflow_data_key = f'workflow:{unique_id}:data'
        self.workflow_status_key = f'workflow:{unique_id}:status'
        self.workflow_event_key = f'workflow:{unique_id}:event'
        self.workflow_input_key = f'workflow:{unique_id}:input'
        self.workflow_stop_key = f'workflow:{unique_id}:stop'
        self.workflow_expire_time = settings.get_workflow_conf().timeout * 60 + 60

    def set_workflow_data(self, data: dict):
        self.redis_client.set(self.workflow_data_key, data, expiration=self.workflow_expire_time)

    def get_workflow_data(self) -> dict:
        return self.redis_client.get(self.workflow_data_key)

    def set_workflow_status(self, status: int, reason: str = None):
        self.redis_client.set(self.workflow_status_key,
                              {'status': status, 'reason': reason, 'time': time.time()},
                              expiration=None)
        self.workflow_cache.clear()
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            # 消息事件和状态key可能还需要消费
            self.redis_client.delete(self.workflow_data_key)
            self.redis_client.delete(self.workflow_input_key)

    def get_workflow_status(self, user_cache: bool = True) -> dict | None:
        # if user_cache and self.workflow_cache.get(self.workflow_status_key):
        #     return self.workflow_cache.get(self.workflow_status_key)
        workflow_status = self.redis_client.get(self.workflow_status_key)
        self.workflow_cache.setdefault(self.workflow_status_key, workflow_status)
        return workflow_status

    def clear_workflow_status(self):
        self.redis_client.delete(self.workflow_status_key)
        self.redis_client.delete(self.workflow_stop_key)
        self.redis_client.delete(self.workflow_data_key)

    def insert_workflow_response(self, event: dict):
        self.redis_client.rpush(self.workflow_event_key, json.dumps(event), expiration=self.workflow_expire_time)

    def get_workflow_response(self) -> ChatResponse | None:
        response = self.redis_client.lpop(self.workflow_event_key)
        if response:
            response = ChatResponse(**json.loads(response))
            if ((response.category == WorkflowEventType.NodeRun.value and response.type == 'end'
                 and response.message and response.message.get('node_id', '').startswith('end_')) or
                    (response.category in [WorkflowEventType.UserInput.value, WorkflowEventType.OutputWithChoose.value
                        , WorkflowEventType.OutputWithInput.value])):
                # 如果是结束节点或者输入事件，清空状态缓存
                self.workflow_cache.clear()
        return response

    def build_chat_response(self, category, category_type, message, extra=None, files=None):
        return ChatResponse(
            user_id=self.user_id,
            chat_id=self.chat_id,
            flow_id=self.workflow_id,
            type=category_type,
            message=message,
            category=category,
            extra=extra,
            files=files,
        )

    def parse_workflow_failed(self, status_info: dict) -> ChatResponse | None:
        if status_info['reason'].find('-- has run more than the maximum number of times') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            {'code': WorkFlowNodeRunMaxTimesError.Code,
                                             'message': status_info['reason'].split('--')[0]})
        elif status_info['reason'].find('workflow wait user input timeout') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            {'code': WorkFlowWaitUserTimeoutError.Code, 'message': ''})
        elif status_info['reason'].find('-- node params is error') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            {'code': WorkFlowNodeUpdateError.Code,
                                             'message': status_info['reason'].split('--')[0]})
        elif status_info['reason'].find('-- workflow node is update') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            {'code': WorkFlowVersionUpdateError.Code,
                                             'message': status_info['reason'].split('--')[0]})
        elif status_info['reason'].find('stop by user') != -1:
            return None
        else:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            {'code': 500, 'message': status_info['reason']})

    async def get_response_until_break(self) -> AsyncIterator[ChatResponse]:
        """ 不断获取workflow的response，直到遇到运行结束或者待输入 """
        while True:
            # get workflow status
            status_info = self.get_workflow_status()
            if not status_info:
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               {'code': 500, 'message': 'workflow status not found'})
                break
            elif status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                while True:
                    chat_response = self.get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                if status_info['status'] == WorkflowStatus.FAILED.value:
                    error_resp = self.parse_workflow_failed(status_info)
                    if error_resp:
                        yield error_resp
                break
            elif status_info['status'] == WorkflowStatus.INPUT.value:
                while True:
                    chat_response = self.get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                break

            elif status_info['status'] in [WorkflowStatus.WAITING.value,
                                           WorkflowStatus.INPUT_OVER.value] and time.time() - status_info['time'] > 10:
                # 10秒内没有收到状态更新，说明workflow没有启动，可能是celery worker线程数已满
                self.set_workflow_status(WorkflowStatus.FAILED.value, 'workflow task execute busy')
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               {'code': WorkFlowTaskBusyError.Code,
                                                'message': WorkFlowTaskBusyError.Msg})
                break
            elif time.time() - status_info['time'] > 86400:
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               {'code': 500, 'message': 'workflow status not update over 1 day'})
                self.set_workflow_status(WorkflowStatus.FAILED.value, 'workflow status not update over 1 day')
                self.set_workflow_stop()
                break
            else:
                chat_response = self.get_workflow_response()
                if not chat_response:
                    await asyncio.sleep(1)
                    continue
                yield chat_response

    def set_user_input(self, data: dict, message_id: int = None, message_content: str = None):
        if self.chat_id and message_id:
            message_db = ChatMessageDao.get_message_by_id(message_id)
            if message_db:
                self.update_old_message(data, message_db, message_content)
        # 通知异步任务用户输入
        self.redis_client.set(self.workflow_input_key, data, expiration=self.workflow_expire_time)
        return

    def update_old_message(self, user_input: dict, message_db: ChatMessage, message_content: str):
        # 更新输出待输入消息里用户的输入和选择
        old_message = json.loads(message_db.message)
        if message_db.category == WorkflowEventType.OutputWithInput.value:
            old_message['hisValue'] = user_input[old_message['node_id']][old_message['key']]
        elif message_db.category == WorkflowEventType.OutputWithChoose.value:
            old_message['hisValue'] = user_input[old_message['node_id']][old_message['key']]
        elif message_db.category == WorkflowEventType.UserInput.value:
            user_input = user_input[old_message['node_id']]

            # 前端传了用户输入内容则使用前端的内容
            if message_content:
                user_input_message = message_content
            # 说明是表单输入
            elif old_message['input_schema']['tab'] == 'form_input':
                user_input_message = ''
                for key_info in old_message['input_schema']['value']:
                    user_input_message += f"{key_info['value']}:{user_input.get(key_info['key'], '')}\n"
            else:
                # DONE merge_check
                # 说明对话框输入, 需要加下上传的文件信息, 和输入节点的数据结构有关
                user_input_message = user_input[old_message['input_schema']['key']]
                # 以下3行在0527中没有，这里加上
                dialog_files_content = user_input.get('dialog_files_content', [])
                for one in dialog_files_content:
                    user_input_message += f"\n{os.path.basename(one).split('?')[0]}"

            self.save_chat_message(ChatResponse(
                message=user_input_message,
                category='question',
            ))
            return
        message_db.message = json.dumps(old_message, ensure_ascii=False)
        ChatMessageDao.update_message_model(message_db)

    def get_user_input(self) -> dict | None:
        ret = self.redis_client.get(self.workflow_input_key)
        if ret:
            self.redis_client.delete(self.workflow_input_key)
        return ret

    def set_workflow_stop(self):
        from bisheng.worker.workflow.tasks import stop_workflow
        stop_workflow.delay(self.unique_id, self.workflow_id, self.chat_id, self.user_id)

    def get_workflow_stop(self) -> bool | None:
        """ 为了可以及时停止workflow，不做内存的缓存 """
        return self.redis_client.get(self.workflow_stop_key) == 1

    def send_chat_response(self, chat_response: ChatResponse):
        """ 发送聊天消息 """
        self.insert_workflow_response(chat_response.dict())

        # 判断下是否需要停止workflow, 流式输出时不判断，查询太频繁，而且也停不掉workflow
        if chat_response.category == WorkflowEventType.StreamMsg.value:
            return
        if self.workflow and self.get_workflow_stop():
            self.workflow.stop()

    def save_chat_message(self, chat_response: ChatResponse, source_documents=None) -> int | str | None:
        """  save chat message to database
        return message id
        """
        if not self.chat_id:
            # 生成一个假的消息id防止前端消息渲染重复
            return uuid.uuid4().hex

        # 判断溯源
        if source_documents:
            result = {}
            extra = {}
            if isinstance(source_documents, Document):
                result = source_documents
            source, result = sync_judge_source(result, source_documents, self.chat_id, extra)
            chat_response.source = source
            chat_response.extra = json.dumps(extra, ensure_ascii=False)

        message = ChatMessageDao.insert_one(ChatMessage(
            user_id=self.user_id,
            chat_id=self.chat_id,
            flow_id=self.workflow_id,
            type=chat_response.type,

            is_bot=chat_response.is_bot,
            source=chat_response.source,
            message=chat_response.message if isinstance(chat_response.message, str) else json.dumps(
                chat_response.message, ensure_ascii=False),
            extra=chat_response.extra,
            category=chat_response.category,
            files=json.dumps(chat_response.files, ensure_ascii=False)
        ))

        # 如果是文档溯源，处理召回的chunk
        if chat_response.source not in [0, 4]:
            sync_process_source_document(source_documents, self.chat_id, message.id, chat_response.message.get('msg'))

        # 判断是否需要新建会话
        if not self.create_session and chat_response.category != WorkflowEventType.UserInput.value:
            # 没有会话数据则新插入一个会话
            if not MessageSessionDao.get_one(self.chat_id):
                db_workflow = FlowDao.get_flow_by_id(self.workflow_id)
                MessageSessionDao.insert_one(MessageSession(
                    chat_id=self.chat_id,
                    flow_id=self.workflow_id,
                    flow_name=db_workflow.name,
                    flow_type=FlowType.WORKFLOW.value,
                    user_id=self.user_id,
                ))
            self.create_session = True

        return message.id

    def on_node_start(self, data: NodeStartData):
        """ node start event """
        logger.debug(f'node start: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category=WorkflowEventType.NodeRun.value,
                         type='start',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_node_end(self, data: NodeEndData):
        """ node end event """
        logger.debug(f'node end: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category=WorkflowEventType.NodeRun.value,
                         type='end',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_user_input(self, data: UserInputData):
        """ user input event """
        logger.debug(f'user input: {data}')
        chat_response = ChatResponse(message=data.dict(),
                                     category=WorkflowEventType.UserInput.value,
                                     type='over',
                                     flow_id=self.workflow_id,
                                     chat_id=self.chat_id)
        msg_id = self.save_chat_message(chat_response)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_guide_word(self, data: GuideWordData):
        """ guide word event """
        logger.debug(f'guide word: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category=WorkflowEventType.GuideWord.value,
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_guide_question(self, data: GuideQuestionData):
        """ guide question event """
        logger.debug(f'guide question: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category=WorkflowEventType.GuideQuestion.value,
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_output_msg(self, data: OutputMsgData):
        logger.debug(f'output msg: {data}')
        chat_response = ChatResponse(message=data.dict(exclude={'source_documents'}),
                                     category=WorkflowEventType.OutputMsg.value,
                                     extra='',
                                     type='over',
                                     flow_id=self.workflow_id,
                                     chat_id=self.chat_id,
                                     files=data.files)
        msg_id = self.save_chat_message(chat_response, source_documents=data.source_documents)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_stream_msg(self, data: StreamMsgData):
        logger.debug(f'stream msg: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category=WorkflowEventType.StreamMsg.value,
                         extra='',
                         type='stream',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_stream_over(self, data: StreamMsgOverData):
        logger.debug(f'stream over: {data}')
        # 替换掉minio的share前缀，通过nginx转发  ugly solve
        minio_share = settings.get_minio_conf().sharepoint
        data.msg = data.msg.replace(f"http://{minio_share}", "")
        chat_response = ChatResponse(message=data.dict(exclude={'source_documents'}),
                                     category=WorkflowEventType.StreamMsg.value,
                                     extra='',
                                     type='end',
                                     flow_id=self.workflow_id,
                                     chat_id=self.chat_id)
        msg_id = self.save_chat_message(chat_response, source_documents=data.source_documents)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_output_choose(self, data: OutputMsgChooseData):
        logger.debug(f'output choose: {data}')
        chat_response = ChatResponse(message=data.dict(exclude={'source_documents'}),
                                     category=WorkflowEventType.OutputWithChoose.value,
                                     extra='',
                                     type='over',
                                     flow_id=self.workflow_id,
                                     chat_id=self.chat_id,
                                     files=data.files)
        msg_id = self.save_chat_message(chat_response, source_documents=data.source_documents)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_output_input(self, data: OutputMsgInputData):
        logger.debug(f'output input: {data}')
        chat_response = ChatResponse(message=data.dict(exclude={'source_documents'}),
                                     category=WorkflowEventType.OutputWithInput.value,
                                     extra='',
                                     type='over',
                                     flow_id=self.workflow_id,
                                     chat_id=self.chat_id,
                                     files=data.files)
        msg_id = self.save_chat_message(chat_response, source_documents=data.source_documents)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)
