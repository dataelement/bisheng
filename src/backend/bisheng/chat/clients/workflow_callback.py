import asyncio

from bisheng.api.v1.schemas import ChatResponse
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import NodeStartData, NodeEndData, UserInputData, GuideWordData, GuideQuestionData, \
    OutputMsgData


class WorkflowWsCallback(BaseCallback):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.websocket = kwargs.get('websocket')
        self.chat_id = kwargs.get('chat_id')
        self.workflow_id = kwargs.get('workflow_id')
        self.user_id = kwargs.get('user_id')

    def send_chat_response(self, chat_response: ChatResponse):
        loop = asyncio.get_event_loop()
        coroutine = self.websocket.send_json(chat_response.dict())
        asyncio.run_coroutine_threadsafe(coroutine, loop)

    def on_node_start(self, data: NodeStartData):
        """ node start event """
        print(f"node start: {data}")
        self.send_chat_response(ChatResponse(
            message=data.dict(),
            category='node_run',
            type='start',
            flow_id=self.workflow_id,
            chat_id=self.chat_id))

    def on_node_end(self, data: NodeEndData):
        """ node end event """
        print(f"node end: {data}")
        self.send_chat_response(ChatResponse(
            message=data.dict(),
            category='node_run',
            type='end',
            flow_id=self.workflow_id,
            chat_id=self.chat_id))

    def on_user_input(self, data: UserInputData):
        """ user input event """
        print(f"user input: {data}")
        self.send_chat_response(ChatResponse(
            message=data.dict(),
            category='user_input',
            type='end',
            flow_id=self.workflow_id,
            chat_id=self.chat_id))

    def on_guide_word(self, data: GuideWordData):
        """ guide word event """
        print(f"guide word: {data}")
        self.send_chat_response(ChatResponse(
            message=data.guide_word,
            category='guide_word',
            type='end',
            flow_id=self.workflow_id,
            chat_id=self.chat_id))

    def on_guide_question(self, data: GuideQuestionData):
        """ guide question event """
        print(f"guide question: {data}")
        self.send_chat_response(ChatResponse(
            message=data.guide_question,
            category='guide_question',
            type='end',
            flow_id=self.workflow_id,
            chat_id=self.chat_id))

    def on_output_msg(self, data: OutputMsgData):
        print(f"output msg: {data}")
        self.send_chat_response(ChatResponse(
            message=data.msg,
            category='output_msg',
            extra=data.dict(),
            type='end',
            flow_id=self.workflow_id,
            chat_id=self.chat_id))
