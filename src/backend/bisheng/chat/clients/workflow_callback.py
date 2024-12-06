import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any, Callable, Coroutine, List, cast

from loguru import logger

from bisheng.api.v1.schemas import ChatResponse
from bisheng.chat.utils import sync_judge_source, sync_process_source_document
from bisheng.database.models.message import ChatMessageDao, ChatMessage, ChatMessageType
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import (GuideQuestionData, GuideWordData, NodeEndData,
                                             NodeStartData, OutputMsgChooseData, OutputMsgData,
                                             OutputMsgInputData, UserInputData, StreamMsgData, StreamMsgOverData)


def _run_coros(coros: List[Coroutine[Any, Any, Any]]) -> None:
    if hasattr(asyncio, 'Runner'):
        # Python 3.11+
        # Run the coroutines in a new event loop, taking care to
        # - install signal handlers
        # - run pending tasks scheduled by `coros`
        # - close asyncgens and executors
        # - close the loop
        with asyncio.Runner() as runner:
            # Run the coroutine, get the result
            for coro in coros:
                try:
                    runner.run(coro)
                except Exception as e:
                    logger.warning(f'Error in callback coroutine: {repr(e)}')

            # Run pending tasks scheduled by coros until they are all done
            while pending := asyncio.all_tasks(runner.get_loop()):
                runner.run(asyncio.wait(pending))
    else:
        # Before Python 3.11 we need to run each coroutine in a new event loop
        # as the Runner api is not available.
        for coro in coros:
            try:
                asyncio.run(coro)
            except Exception as e:
                logger.warning(f'Error in callback coroutine: {repr(e)}')


class WorkflowWsCallback(BaseCallback):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.websocket = kwargs.get('websocket')
        self.chat_id = kwargs.get('chat_id')
        self.workflow_id = kwargs.get('workflow_id')
        self.user_id = kwargs.get('user_id')

    def send_chat_response(self, chat_response: ChatResponse):
        with ThreadPoolExecutor(1) as executor:
            executor.submit(cast(Callable,
                                 copy_context().run), _run_coros,
                            [self.websocket.send_json(chat_response.dict())]).result()

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
            source=chat_response.source,  # todo 溯源功能
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
