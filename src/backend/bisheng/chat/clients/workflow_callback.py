import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any, Callable, Coroutine, List, cast

from bisheng.api.v1.schemas import ChatResponse
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import (GuideQuestionData, GuideWordData, NodeEndData,
                                             NodeStartData, OutputMsgChooseData, OutputMsgData,
                                             OutputMsgInputData, UserInputData)
from loguru import logger


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

    def on_node_start(self, data: NodeStartData):
        """ node start event """
        print(f'node start: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='node_run',
                         type='start',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_node_end(self, data: NodeEndData):
        """ node end event """
        print(f'node end: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='node_run',
                         type='end',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_user_input(self, data: UserInputData):
        """ user input event """
        print(f'user input: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='user_input',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_guide_word(self, data: GuideWordData):
        """ guide word event """
        print(f'guide word: {data}')
        self.send_chat_response(
            ChatResponse(message=data.guide_word,
                         category='guide_word',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_guide_question(self, data: GuideQuestionData):
        """ guide question event """
        print(f'guide question: {data}')
        self.send_chat_response(
            ChatResponse(message=data.guide_question,
                         category='guide_question',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id))

    def on_output_msg(self, data: OutputMsgData):
        print(f'output msg: {data}')
        msg_type = 'stream' if data.stream else 'over'
        self.send_chat_response(
            ChatResponse(message=data,
                         category='output_msg',
                         extra='',
                         type=msg_type,
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id,
                         files=data.files))

    def on_output_choose(self, data: OutputMsgChooseData):
        print(f'output choose: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='output_choose_msg',
                         extra='',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id,
                         files=data.files))

    def on_output_input(self, data: OutputMsgInputData):
        print(f'output input: {data}')
        self.send_chat_response(
            ChatResponse(message=data.dict(),
                         category='output_input_msg',
                         extra='',
                         type='over',
                         flow_id=self.workflow_id,
                         chat_id=self.chat_id,
                         files=data.files))
