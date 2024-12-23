import json
import time

from cachetools import TTLCache
from loguru import logger

from bisheng.api.v1.schemas import ChatResponse
from bisheng.cache.redis import redis_client
from bisheng.chat.utils import sync_judge_source, sync_process_source_document
from bisheng.database.models.message import ChatMessageDao, ChatMessage, ChatMessageType
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
                              expiration=self.workflow_expire_time)
        self.workflow_cache.clear()
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            # 消息事件和状态key可能还需要消费
            self.redis_client.delete(self.workflow_data_key)
            self.redis_client.delete(self.workflow_input_key)

    def get_workflow_status(self, user_cache: bool = True) -> dict | None:
        if user_cache and self.workflow_cache.get(self.workflow_status_key):
            return self.workflow_cache.get(self.workflow_status_key)
        workflow_status = self.redis_client.get(self.workflow_status_key)
        self.workflow_cache.setdefault(self.workflow_status_key, workflow_status)
        return workflow_status

    def insert_workflow_response(self, event: dict):
        self.redis_client.rpush(self.workflow_event_key, json.dumps(event), expiration=self.workflow_expire_time)

    def get_workflow_response(self):
        response = self.redis_client.lpop(self.workflow_event_key)
        if response:
            response = json.loads(response)
            if (response.get('category') == 'node_run' and response.get('type') == 'end'
                    and response.get('message', {}).get('node_id', '').startswith('end_')):
                # 如果是结束节点，清空状态缓存
                self.workflow_cache.clear()
        return response

    def set_user_input(self, data: dict):
        self.redis_client.set(self.workflow_input_key, data, expiration=self.workflow_expire_time)

    def get_user_input(self) -> dict | None:
        ret = self.redis_client.get(self.workflow_input_key)
        if ret:
            self.redis_client.delete(self.workflow_input_key)
        return ret

    def set_workflow_stop(self):
        self.redis_client.set(self.workflow_stop_key, 1, expiration=self.workflow_expire_time)

    def get_workflow_stop(self) -> int | None:
        """ 为了可以及时停止workflow，不做内存的缓存 """
        return self.redis_client.get(self.workflow_stop_key)

    def send_chat_response(self, chat_response: ChatResponse):
        """ 发送聊天消息 """
        self.insert_workflow_response(chat_response.dict())

        # 判断下是否需要停止workflow, 流式输出时不判断，查询太频繁，而且也停不掉workflow
        if chat_response.category == 'stream_msg':
            return
        if self.workflow and self.get_workflow_stop() == 1:
            self.workflow.stop()

    def save_chat_message(self, chat_response: ChatResponse, source_documents=None) -> int | None:
        """  save chat message to database
        return message id
        """
        if not self.chat_id:
            return

        # 判断溯源
        if source_documents:
            result = {}
            extra = {}
            if len(source_documents) == 1:
                result = source_documents[0]
            source, result = sync_judge_source(result, source_documents, self.chat_id, extra)
            chat_response.source = source
            chat_response.extra = json.dumps(extra, ensure_ascii=False)

        message = ChatMessageDao.insert_one(ChatMessage(
            user_id=self.user_id,
            chat_id=self.chat_id,
            flow_id=self.workflow_id,
            type=ChatMessageType.WORKFLOW.value,

            is_bot=chat_response.is_bot,
            source=chat_response.source,
            message=json.dumps(chat_response.message, ensure_ascii=False),
            extra=chat_response.extra,
            category=chat_response.category,
            files=json.dumps(chat_response.files, ensure_ascii=False)
        ))

        # 如果是文档溯源，处理召回的chunk
        if chat_response.source not in [0, 4]:
            sync_process_source_document(source_documents, self.chat_id, message.id, chat_response.message.get('msg'))

        return message.id

    def on_node_start(self, data: NodeStartData):
        """ node start event """
        logger.debug(f'node start: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='node_run',
                         type='start',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_node_end(self, data: NodeEndData):
        """ node end event """
        logger.debug(f'node end: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='node_run',
                         type='end',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_user_input(self, data: UserInputData):
        """ user input event """
        logger.debug(f'user input: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='user_input',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_guide_word(self, data: GuideWordData):
        """ guide word event """
        logger.debug(f'guide word: {data}')
        self.send_chat_response(
            ChatResponse(message=data.guide_word,
                         category='guide_word',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_guide_question(self, data: GuideQuestionData):
        """ guide question event """
        logger.debug(f'guide question: {data}')
        self.send_chat_response(
            ChatResponse(message=data.guide_question,
                         category='guide_question',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_output_msg(self, data: OutputMsgData):
        logger.debug(f'output msg: {data}')
        chat_response = ChatResponse(message=data.dict(exclude={'source_documents'}),
                                     category='output_msg',
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
                         category='stream_msg',
                         extra='',
                         type='stream',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_stream_over(self, data: StreamMsgOverData):
        logger.debug(f'stream over: {data}')
        chat_response = ChatResponse(message=data.dict(exclude={'source_documents'}),
                                     category='stream_msg',
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
                                     category='output_choose_msg',
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
                                     category='output_input_msg',
                                     extra='',
                                     type='over',
                                     flow_id=self.workflow_id,
                                     chat_id=self.chat_id,
                                     files=data.files)
        msg_id = self.save_chat_message(chat_response, source_documents=data.source_documents)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)
