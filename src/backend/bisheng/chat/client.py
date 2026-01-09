import json
import time
from queue import Queue
from typing import Dict, Callable, List

from fastapi import WebSocket, Request
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage, ToolMessage
from loguru import logger

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.assistant import (AssistantDeletedError, AssistantNotOnlineError,
                                              AssistantOtherError)
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData, ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessageDao, ChatMessage as ChatMessageModel
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.utils import get_request_ip
from bisheng.utils.threadpool import thread_pool
from bisheng_langchain.gpts.message_types import LiberalToolMessage


class ChatClient:
    def __init__(self, request: Request, client_key: str, client_id: str, chat_id: str, user_id: int,
                 login_user: UserPayload, work_type: WorkType, websocket: WebSocket, **kwargs):
        self.request = request
        self.client_key = client_key
        self.client_id = client_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.login_user = login_user
        self.work_type = work_type
        self.websocket = websocket
        self.kwargs = kwargs

        # Business Custom Parameters
        self.db_assistant = None
        self.gpts_agent: AssistantAgent | None = None
        self.gpts_async_callback = None
        self.chat_history = []
        # Incoming when talking to the model Full Historical Dialogue Round Count
        self.latest_history_num = 10
        self.gpts_conf = settings.get_from_db('gpts')
        # Asynchronous Task List
        self.task_ids = []
        # A queue of streaming outputs to accept the content of the streaming output, processing newquestionEmpty at all times
        self.stream_queue = Queue()

    async def close(self):
        pass

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage):
        await self.websocket.send_json(message.dict())

    async def handle_message(self, message: Dict[any, any]):
        logger.info(f'client_id={self.client_key} handle_message start, message: {message}')
        trace_id = trace_id_var.get()
        # Handling messages from clients, Submit to Thread Pool for Execution
        if self.work_type == WorkType.GPTS:
            thread_pool.submit(trace_id,
                               self.wrapper_task,
                               trace_id,
                               self.handle_gpts_message,
                               message,
                               trace_id=trace_id)
            # await self.handle_gpts_message(message)

    async def wrapper_task(self, task_id: str, fn: Callable, *args, **kwargs):
        # The wrapper handler function is an asynchronous task
        self.task_ids.append(task_id)
        start_time = time.time()
        try:
            # Execute Handling Functions
            await fn(*args, **kwargs)
        except Exception as e:
            logger.exception("handle message error")
        finally:
            # When the execution is complete, the task will beidRemove from list
            self.task_ids.remove(task_id)
            end_time = time.time()
            await telemetry_service.log_event(user_id=self.user_id,
                                              event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                                              trace_id=trace_id_var.get(),
                                              event_data=ApplicationProcessEventData(
                                                  app_id=self.client_id,
                                                  app_name=self.db_assistant.name if self.db_assistant else "",
                                                  app_type=ApplicationTypeEnum.ASSISTANT,
                                                  chat_id=self.chat_id,

                                                  start_time=int(start_time),
                                                  end_time=int(end_time),
                                                  process_time=int((end_time - start_time) * 1000)
                                              ))

    async def add_message(self, msg_type: str, message: str, category: str, remark: str = ''):
        self.chat_history.append({
            'category': category,
            'message': message,
            'remark': remark
        })
        if not self.chat_id:
            # debugMode does not need to save history
            return
        is_bot = 0 if msg_type == 'human' else 1
        msg = ChatMessageDao.insert_one(ChatMessageModel(
            is_bot=is_bot,
            source=0,
            message=message,
            category=category,
            type=msg_type,
            extra=json.dumps({'client_key': self.client_key}, ensure_ascii=False),
            flow_id=self.client_id,
            chat_id=self.chat_id,
            user_id=self.user_id,
            remark=remark,
        ))
        # Log Audit Logs, Is New Session
        if len(self.chat_history) <= 1:
            MessageSessionDao.insert_one(MessageSession(
                chat_id=self.chat_id,
                flow_id=self.client_id,
                flow_name=self.db_assistant.name,
                flow_type=FlowType.ASSISTANT.value,
                user_id=self.user_id,
            ))

            # RecordTelemetryJournal
            await telemetry_service.log_event(user_id=self.user_id,
                                              event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                                              trace_id=trace_id_var.get(),
                                              event_data=NewMessageSessionEventData(
                                                  session_id=self.chat_id,
                                                  app_id=self.client_id,
                                                  source="platform",
                                                  app_name=self.db_assistant.name,
                                                  app_type=ApplicationTypeEnum.ASSISTANT
                                              )
                                              )
            AuditLogService.create_chat_assistant(self.login_user, get_request_ip(self.request), self.client_id)
        return msg

    async def send_response(self, category: str, msg_type: str, message: str, intermediate_steps: str = '',
                            message_id: int = None):
        is_bot = 0 if msg_type == 'human' else 1
        await self.send_json(ChatResponse(
            message_id=message_id,
            category=category,
            type=msg_type,
            is_bot=is_bot,
            message=message,
            user_id=self.user_id,
            flow_id=self.client_id,
            chat_id=self.chat_id,
            extra=json.dumps({'client_key': self.client_key}, ensure_ascii=False),
            intermediate_steps=intermediate_steps,
        ))

    async def init_gpts_agent(self):
        await self.init_chat_history()
        await self.init_gpts_callback()
        try:
            # Processing Intelligent Assistant Business
            if self.chat_id and self.gpts_agent is None:
                # Conversation businessagentFixed generation from database data,Don't change every time
                assistant = AssistantDao.get_one_assistant(self.client_id)
                if not assistant:
                    raise AssistantDeletedError()
                    # Under JudgmentagentOnline or not
                if assistant.status != AssistantStatus.ONLINE.value:
                    raise AssistantNotOnlineError()
            elif not self.chat_id:
                # The debug interface is regenerated without testing
                assistant = AssistantDao.get_one_assistant(self.client_id)
                if not assistant:
                    raise AssistantDeletedError()

            # await self.websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
            # raise IgnoreException(f'get assistant info error: {str(e)}')

            if self.chat_id and self.gpts_agent is None:
                self.db_assistant = assistant
                # Conversation businessagentFixed generation from database data,Don't change every time
                self.gpts_agent = AssistantAgent(assistant, self.chat_id, invoke_user_id=self.user_id)
                await self.gpts_agent.init_assistant(self.gpts_async_callback)
            elif not self.chat_id:
                self.db_assistant = assistant
                # The debugging interface is regenerated every time
                self.gpts_agent = AssistantAgent(assistant, self.chat_id, invoke_user_id=self.user_id)
                await self.gpts_agent.init_assistant(self.gpts_async_callback)

        except BaseErrorCode as e:
            logger.exception("get assistant info error")
            raise e
        except Exception as e:
            logger.exception("get assistant info error")
            raise AssistantOtherError(exception=e)

    async def init_chat_history(self):
        # Initialization history, not empty or no reinitialization
        if len(self.chat_history) > 0:
            return
        # Load Historical Sessions from Database
        if self.chat_id:
            res = ChatMessageDao.get_messages_by_chat_id(self.chat_id,
                                                         ['question', 'answer', 'tool_call', 'tool_result'],
                                                         self.latest_history_num * 4)
            for one in res:
                self.chat_history.append({
                    'message': one.message,
                    'category': one.category,
                    'remark': one.remark
                })

    async def get_latest_history(self) -> List[BaseMessage]:
        # Invalid historical messages need to be culled and only complete Q&A sessions are included
        tmp = []
        find_i = 0
        is_answer = True
        # Get from Chat History
        for i in range(len(self.chat_history) - 1, -1, -1):
            one_item = self.chat_history[i]
            if find_i >= self.latest_history_num:
                break
            # Answers without interruptions
            if one_item['category'] == 'answer' and one_item.get('remark') != 'break_answer' and is_answer:
                tmp.insert(0, AIMessage(content=one_item['message']))
                is_answer = False
            elif one_item['category'] == 'question' and not is_answer:
                tmp.insert(0, HumanMessage(content=json.loads(one_item['message'])['input']))
                is_answer = True
                find_i += 1
            elif one_item['category'] == 'tool_call':
                tmp.insert(0, AIMessage(**json.loads(one_item['message'])))
            elif one_item['category'] == 'tool_result':
                tmp.insert(0, LiberalToolMessage(**json.loads(one_item['message'])))

        return tmp

    async def init_gpts_callback(self):
        if self.gpts_async_callback is not None:
            return
        async_callbacks = [AsyncGptsDebugCallbackHandler(**{
            'websocket': self.websocket,
            'flow_id': self.client_id,
            'chat_id': self.chat_id,
            'user_id': self.user_id,
            'stream_queue': self.stream_queue,
        })]
        self.gpts_async_callback = async_callbacks

    async def stop_handle_message(self, message: Dict[any, any]):
        # Abort Streaming Output, Because the latest taskidis to abort the task.id, you can't cancel yourself
        logger.info(f'need stop agent, client_key: {self.client_key}, message: {message}')

        # Processing function before abort
        thread_pool.cancel_task(self.task_ids[:-1])

        # Write streaming output to database
        answer = ''
        reasoning_answer = ''
        while not self.stream_queue.empty():
            msg = self.stream_queue.get()
            if msg.get('type') == 'answer':
                answer += msg.get('content', '')
            elif msg.get('type') == 'reasoning':
                reasoning_answer += msg.get('content', '')

        # If there is streaming output, record the streaming output to the database
        if reasoning_answer.split():
            res = await self.add_message('bot', answer, 'reasoning_answer', 'break_answer')
            await self.send_response('reasoning_answer', 'end', '', message_id=res.id if res else None)
        if answer.strip():
            res = await self.add_message('bot', answer, 'answer', 'break_answer')
            await self.send_response('answer', 'end', '', message_id=res.id if res else None)
        await self.send_response('processing', 'close', '')

    async def clear_stream_queue(self):
        while not self.stream_queue.empty():
            self.stream_queue.get()

    async def handle_gpts_message(self, message: Dict[any, any]):
        if not message:
            return
        logger.debug(f'receive client message, client_key: {self.client_key} message: {message}')
        if message.get('action') == 'stop':
            await self.stop_handle_message(message)
            return

        try:
            await self.send_response('processing', 'begin', '')
            # Empty the streaming queue to prevent contamination of the previous answer
            await self.clear_stream_queue()
            inputs = message.get('inputs', {})
            input_msg = inputs.get('input')
            if not input_msg:
                # Session needs to be switched
                logger.debug(f'need switch agent, client_key: {self.client_key} inputs: {inputs}')
                self.client_id = inputs.get('data').get('id')
                self.chat_id = inputs.get('data').get('chatId')
                self.gpts_agent = None
                self.gpts_async_callback = None
                self.chat_history = []
                await self.init_gpts_agent()
                return

            # Inisialisasiagent
            await self.init_gpts_agent()

            # Write user issue to database
            await self.add_message('human', json.dumps(inputs, ensure_ascii=False), 'question')

            # Get callback history
            chat_history = await self.get_latest_history()
            # RecallagentGet Results
            result = await self.gpts_agent.run(input_msg, chat_history, self.gpts_async_callback)
            logger.debug(f'gpts agent {self.client_key} result: {result}')
            answer = result[-1].content

            # Record contains
            new_history = result[len(chat_history):-1]
            for one in new_history:
                if isinstance(one, AIMessage):
                    _ = await self.add_message('bot', one.json(), 'tool_call')
                elif isinstance(one, LiberalToolMessage) or isinstance(one, ToolMessage):
                    _ = await self.add_message('bot', one.json(), 'tool_result')
                else:
                    logger.warning("unexpected message type")

            answer_end_type = 'end'
            # If it's streaming,llmthen useend_coverEnd, Overwrite previous streamed output
            if getattr(self.gpts_agent.llm, 'streaming', False):
                answer_end_type = 'end_cover'

            # Get from Queuereasoning content
            reasoning_content = ''
            while not self.stream_queue.empty():
                msg = self.stream_queue.get()
                if msg.get('type') == 'reasoning':
                    reasoning_content += msg.get('content')

            res = await self.add_message('bot', reasoning_content, 'reasoning_answer')
            res = await self.add_message('bot', answer, 'answer')
            await self.send_response('answer', 'start', '')
            await self.send_response('answer', answer_end_type, answer, message_id=res.id if res else None)
            logger.info(f'gptsAgentOver assistant_id:{self.client_id} chat_id:{self.chat_id} question:{input_msg}')
            logger.info(f'gptsAgentOver assistant_id:{self.client_id} chat_id:{self.chat_id} answer:{answer}')

        except BaseErrorCode as e:
            logger.exception('handle gpts message error: ')
            await self.send_response('system', 'start', '')
            await e.websocket_close_message(websocket=self.websocket, close_ws=False)
        except Exception as e:
            e = AssistantOtherError(exception=e)
            logger.exception('handle gpts message error: ')
            await self.send_response('system', 'start', '')
            await e.websocket_close_message(websocket=self.websocket, close_ws=False)
        finally:
            await self.send_response('processing', 'close', '')
