import asyncio
import json
import os
import time
import uuid
from typing import AsyncIterator, Iterator

from langchain_core.documents import Document
from loguru import logger

from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import ChatResponse
from bisheng.chat.utils import sync_judge_source, sync_process_source_document
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.errcode.flow import WorkFlowNodeRunMaxTimesError, WorkFlowWaitUserTimeoutError, \
    WorkFlowNodeUpdateError, WorkFlowVersionUpdateError, WorkFlowTaskBusyError, WorkFlowTaskOtherError
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessageDao, ChatMessage
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.utils.threadpool import thread_pool
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import NodeStartData, NodeEndData, UserInputData, GuideWordData, GuideQuestionData, \
    OutputMsgData, StreamMsgData, StreamMsgOverData, OutputMsgChooseData, OutputMsgInputData
from bisheng.workflow.common.workflow import WorkflowStatus


class RedisCallback(BaseCallback):

    def __init__(self, unique_id: str, workflow_id: str, chat_id: str, user_id: int):
        super(RedisCallback, self).__init__()
        # Unique for asynchronous tasksID
        self.unique_id = unique_id
        self.workflow_id = workflow_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.workflow = None
        self.create_session = False

        self.redis_client = get_redis_client_sync()
        self.workflow_data_key = f'workflow:{unique_id}:data'
        self.workflow_status_key = f'workflow:{unique_id}:status'
        self.workflow_event_key = f'workflow:{unique_id}:event'
        self.workflow_input_key = f'workflow:{unique_id}:input'
        self.workflow_stop_key = f'workflow:{unique_id}:stop'
        self.workflow_expire_time = settings.get_workflow_conf().timeout * 60 + 60

    def set_workflow_data(self, data: dict):
        self.redis_client.set(self.workflow_data_key, data, expiration=self.workflow_expire_time)

    async def async_set_workflow_data(self, data: dict):
        await self.redis_client.aset(self.workflow_data_key, data, expiration=self.workflow_expire_time)

    def get_workflow_data(self) -> dict:
        return self.redis_client.get(self.workflow_data_key)

    def set_workflow_status(self, status: str, reason: str = None):
        self.redis_client.set(self.workflow_status_key,
                              {'status': status, 'reason': reason, 'time': time.time()},
                              expiration=3600 * 24 * 7)
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            # Message Events and StatuskeyConsumption may also be required
            self.redis_client.delete(self.workflow_data_key)
            self.redis_client.delete(self.workflow_input_key)

    async def async_set_workflow_status(self, status: str, reason: str = None):
        await self.redis_client.aset(self.workflow_status_key,
                                     {'status': status, 'reason': reason, 'time': time.time()},
                                     expiration=3600 * 24 * 7)
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            # Message Events and StatuskeyConsumption may also be required
            await self.redis_client.adelete(self.workflow_data_key)
            await self.redis_client.adelete(self.workflow_input_key)

    def get_workflow_status(self) -> dict | None:
        workflow_status = self.redis_client.get(self.workflow_status_key)
        return workflow_status

    async def async_get_workflow_status(self) -> dict | None:
        workflow_status = await self.redis_client.aget(self.workflow_status_key)
        return workflow_status

    def clear_workflow_status(self):
        self.redis_client.delete(self.workflow_status_key)
        self.redis_client.delete(self.workflow_stop_key)
        self.redis_client.delete(self.workflow_data_key)

    async def async_clear_workflow_status(self):
        await self.redis_client.adelete(self.workflow_status_key)
        await self.redis_client.adelete(self.workflow_stop_key)
        await self.redis_client.adelete(self.workflow_data_key)

    def insert_workflow_response(self, event: dict):
        self.redis_client.rpush(self.workflow_event_key, json.dumps(event), expiration=self.workflow_expire_time)

    def get_workflow_response(self) -> ChatResponse | None:
        response = self.redis_client.lpop(self.workflow_event_key)
        if self.get_workflow_stop():
            self.redis_client.delete(self.workflow_event_key)
            return None
        if response:
            response = ChatResponse(**json.loads(response))
        return response

    async def async_get_workflow_response(self) -> ChatResponse | None:
        response = await self.redis_client.alpop(self.workflow_event_key)
        if await self.async_get_workflow_stop():
            await self.redis_client.adelete(self.workflow_event_key)
            return None
        if response:
            response = ChatResponse(**json.loads(response))
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
                                            message=WorkFlowNodeRunMaxTimesError(
                                                exception=status_info['reason'].split('--')[0]).to_dict())
        elif status_info['reason'].find('workflow wait user input timeout') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            message=WorkFlowWaitUserTimeoutError().to_dict())
        elif status_info['reason'].find('-- node params is error') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            message=WorkFlowNodeUpdateError(
                                                exception=status_info['reason'].split('--')[0]).to_dict())
        elif status_info['reason'].find('-- workflow node is update') != -1:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            message=WorkFlowVersionUpdateError(
                                                exception=status_info['reason'].split('--')[0]).to_dict())
        elif status_info['reason'].find('stop by user') != -1:
            return None
        else:
            return self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                            WorkFlowTaskOtherError(exception=status_info['reason']).to_dict())

    def sync_get_response_until_break(self) -> Iterator[ChatResponse]:
        while True:
            # get workflow status
            status_info = self.get_workflow_status()
            if not status_info:
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               message=WorkFlowTaskOtherError(
                                                   exception=Exception("workflow status not found")).to_dict())
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
                # 10No status update received in seconds, descriptionworkflowNot started, could becelery workerThreads full
                self.set_workflow_status(WorkflowStatus.FAILED.value, 'workflow task execute busy')
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               message=WorkFlowTaskBusyError().to_dict())
                break
            elif time.time() - status_info['time'] > 86400:
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               WorkFlowTaskOtherError(
                                                   exception=Exception(
                                                       "workflow status not update over 1 day")).to_dict())
                self.set_workflow_status(WorkflowStatus.FAILED.value, 'workflow status not update over 1 day')
                self.set_workflow_stop()
                break
            else:
                chat_response = self.get_workflow_response()
                if not chat_response:
                    time.sleep(1)
                    continue
                yield chat_response

    async def get_response_until_break(self) -> AsyncIterator[ChatResponse]:
        """ Continuous accessworkflowright of privacyresponseuntil the end of the run is encountered or pending entry """
        while True:
            # get workflow status
            status_info = await self.async_get_workflow_status()
            if not status_info:
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               message=WorkFlowTaskOtherError(
                                                   exception=Exception("workflow status not found")).to_dict())
                break
            elif status_info['status'] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                while True:
                    chat_response = await self.async_get_workflow_response()
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
                    chat_response = await self.async_get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                break
            elif status_info['status'] in [WorkflowStatus.WAITING.value,
                                           WorkflowStatus.INPUT_OVER.value] and time.time() - status_info['time'] > 10:
                # 10No status update received in seconds, descriptionworkflowNot started, could becelery workerThreads full
                await self.async_set_workflow_status(WorkflowStatus.FAILED.value, 'workflow task execute busy')
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               message=WorkFlowTaskBusyError().to_dict())
                break
            elif time.time() - status_info['time'] > 86400:
                yield self.build_chat_response(WorkflowEventType.Error.value, 'over',
                                               message=WorkFlowTaskOtherError(exception=Exception(
                                                   "workflow status not update over 1 day")).to_dict())
                await self.async_set_workflow_status(WorkflowStatus.FAILED.value,
                                                     'workflow status not update over 1 day')
                await self.async_set_workflow_stop()
                break
            else:
                chat_response = await self.async_get_workflow_response()
                if not chat_response:
                    await asyncio.sleep(0.01)
                    continue
                yield chat_response

    def set_user_input(self, data: dict, message_id: int = None, message_content: str = None):
        if self.chat_id and message_id:
            message_db = ChatMessageDao.get_message_by_id(message_id)
            if message_db:
                self.update_old_message(data, message_db, message_content)
        # Notify Asynchronous Task User Input
        self.redis_client.set(self.workflow_input_key, data, expiration=self.workflow_expire_time)
        return

    async def async_set_user_input(self, data: dict, message_id: int = None, message_content: str = None):
        if self.chat_id and message_id:
            message_db = await ChatMessageDao.aget_message_by_id(message_id)
            if message_db:
                await self.async_update_old_message(data, message_db, message_content)
        # Notify Asynchronous Task User Input
        await self.redis_client.aset(self.workflow_input_key, data, expiration=self.workflow_expire_time)
        return

    @staticmethod
    def _update_old_message(user_input: dict, message_db: ChatMessage, message_content: str):
        """
        if ChatResponse is not None: add new message
        if ChatMessage is not None: update old message
        return ChatResponse | None, ChatMessage | None
        """
        # Update the input and selection of the user in the output to be entered message
        old_message = json.loads(message_db.message)
        if message_db.category == WorkflowEventType.OutputWithInput.value:
            old_message['hisValue'] = user_input[old_message['node_id']][old_message['key']]
        elif message_db.category == WorkflowEventType.OutputWithChoose.value:
            old_message['hisValue'] = user_input[old_message['node_id']][old_message['key']]
        elif message_db.category == WorkflowEventType.UserInput.value:
            user_input = user_input[old_message['node_id']]

            # If the front-end passes user input, the front-end content is used.
            if message_content:
                user_input_message = message_content
            # Instructions are form inputs
            elif old_message['input_schema']['tab'] == 'form_input':
                user_input_message = ''
                for key_info in old_message['input_schema']['value']:
                    user_input_message += f"{key_info['value']}:{user_input.get(key_info['key'], '')}\n"
            else:
                # Description Dialog Input, Uploaded file information needs to be added, It is related to the data structure of the input node.
                user_input_message = user_input[old_message['input_schema']['key']]
                dialog_files_content = user_input.get('dialog_files_content', [])
                for one in dialog_files_content:
                    user_input_message += f"\n{os.path.basename(one).split('?')[0]}"
            return ChatResponse(
                message=user_input_message,
                category='question',
            ), None
        message_db.message = json.dumps(old_message, ensure_ascii=False)
        return None, message_db

    def update_old_message(self, user_input: dict, message_db: ChatMessage, message_content: str):
        chat_response, message = self._update_old_message(user_input, message_db, message_content)
        if chat_response:
            self.save_chat_message(chat_response)
            return
        if message:
            ChatMessageDao.update_message_model(message)

    async def async_update_old_message(self, user_input: dict, message_db: ChatMessage, message_content: str):
        chat_response, message = self._update_old_message(user_input, message_db, message_content)
        if chat_response:
            self.save_chat_message(chat_response)
            return
        if message:
            await ChatMessageDao.aupdate_message_model(message)

    def get_user_input(self) -> dict | None:
        ret = self.redis_client.get(self.workflow_input_key)
        if ret:
            self.redis_client.delete(self.workflow_input_key)
        return ret

    def set_workflow_stop(self):
        from bisheng.worker.workflow.tasks import stop_workflow
        self.redis_client.set(self.workflow_stop_key, 1, expiration=3600 * 24)
        stop_workflow.delay(self.unique_id, self.workflow_id, self.chat_id, self.user_id)

    async def async_set_workflow_stop(self):
        from bisheng.worker.workflow.tasks import stop_workflow
        await self.redis_client.aset(self.workflow_stop_key, 1, expiration=3600 * 24)
        stop_workflow.delay(self.unique_id, self.workflow_id, self.chat_id, self.user_id)

    def get_workflow_stop(self) -> bool | None:
        """ In order to stop in timeworkflow, Do not cache memory """
        return self.redis_client.get(self.workflow_stop_key) == 1

    async def async_get_workflow_stop(self) -> bool | None:
        """ In order to stop in timeworkflow, Do not cache memory """
        return await self.redis_client.aget(self.workflow_stop_key) == 1

    def send_chat_response(self, chat_response: ChatResponse):
        """ Send a chat message """
        self.insert_workflow_response(chat_response.dict())

        # Determine if it needs to be stoppedworkflow, Don't judge when streaming, queries are too frequent and can't be stoppedworkflow
        if chat_response.category == WorkflowEventType.StreamMsg.value:
            return
        if self.workflow and self.get_workflow_stop():
            self.workflow.stop()

    def save_chat_message(self, chat_response: ChatResponse, source_documents=None) -> int | str | None:
        """  save chat message to database
        return message id
        """
        if not self.chat_id:
            # Generate a fake messageidPrevent duplicate front-end message rendering
            return uuid.uuid4().hex

        # Judgment traceability
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

        # If the document is traceable, handle the recallchunk
        if chat_response.source not in [0, 4]:
            thread_pool.submit(f"workflow_source_document_{self.chat_id}",
                               sync_process_source_document,
                               source_documents, self.chat_id, message.id, chat_response.message.get('msg'))

        # Determine if a new session is needed
        if not self.create_session and chat_response.category != WorkflowEventType.UserInput.value:
            # Insert a new session without session data
            if not MessageSessionDao.get_one(self.chat_id):
                db_workflow = FlowDao.get_flow_by_id(self.workflow_id)
                MessageSessionDao.insert_one(MessageSession(
                    chat_id=self.chat_id,
                    flow_id=self.workflow_id,
                    flow_name=db_workflow.name,
                    flow_type=FlowType.WORKFLOW.value,
                    user_id=self.user_id,
                ))

                # RecordTelemetryJournal
                telemetry_service.log_event_sync(user_id=self.user_id,
                                                 event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                                                 trace_id=trace_id_var.get(),
                                                 event_data=NewMessageSessionEventData(
                                                     session_id=self.chat_id,
                                                     app_id=self.workflow_id,
                                                     source="platform",
                                                     app_name=db_workflow.name,
                                                     app_type=ApplicationTypeEnum.WORKFLOW
                                                 )
                                                 )

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
        # Replaceminioright of privacysharePrefix bynginxShare  ugly solve
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
