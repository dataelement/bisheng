import json
from typing import Dict
from uuid import UUID

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler, AsyncGptsLLMCallbackHandler
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import WorkType
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from fastapi import WebSocket, status
from langchain_core.messages import AIMessage
from loguru import logger


class ChatClient:
    def __init__(self, client_key: str, client_id: str, chat_id: str, user_id: int,
                 work_type: WorkType, websocket: WebSocket, **kwargs):
        self.client_key = client_key
        self.client_id = client_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.work_type = work_type
        self.websocket = websocket
        self.kwargs = kwargs

        # 业务自定义参数
        self.gpts_agent: AssistantAgent | None = None

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage):
        await self.websocket.send_json(message.dict())

    async def handle_message(self, message: Dict[any, any]):
        # 处理客户端发过来的信息
        if self.work_type == WorkType.GPTS:
            await self.handle_gpts_message(message)

    async def add_message(self, msg_type: str, message: str, category: str):
        if not self.chat_id:
            # debug模式无需保存历史
            return
        is_bot = 0 if msg_type == 'human' else 1
        ChatMessageDao.insert_one(ChatMessageModel(
            is_bot=is_bot,
            source=0,
            message=message,
            category=category,
            type=msg_type,
            extra=json.dumps({'client_key': self.client_key}, ensure_ascii=False),
            flow_id=self.client_id,
            chat_id=self.chat_id,
            user_id=self.user_id,
        ))

    async def send_response(self, category: str, msg_type: str, message: str, intermediate_steps: str = ''):
        is_bot = 0 if msg_type == 'human' else 1
        await self.send_json(ChatResponse(
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

    async def handle_gpts_message(self, message: Dict[any, any]):
        if not message:
            return
        logger.debug(f'receive client message, client_key: {self.client_key} message: {message}')
        try:
            # 处理智能助手业务
            if self.chat_id and self.gpts_agent is None:
                # 会话业务agent通过数据库数据固定生成,不用每次变化
                assistant = AssistantDao.get_one_assistant(UUID(self.client_id))
                self.gpts_agent = AssistantAgent(assistant, self.chat_id)
                await self.gpts_agent.init_assistant()
            else:
                # 每次都从数据库获取重新构造一个agent
                # TODO zgq：后续可以和前端约定参数，决定是否要重新初始化agent
                assistant = AssistantDao.get_one_assistant(UUID(self.client_id))
                self.gpts_agent = AssistantAgent(assistant, self.chat_id)
                await self.gpts_agent.init_assistant()

        except Exception as e:
            logger.error('agent init error %s' % str(e), exc_info=True)
            await self.websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason='agent init error')
            raise Exception('agent init error')

        if self.chat_id:
            async_callbacks = [AsyncGptsLLMCallbackHandler(**{
                'websocket': self.websocket,
                'flow_id': self.client_id,
                'chat_id': self.chat_id
            })]
        else:
            async_callbacks = [AsyncGptsDebugCallbackHandler(**{
                'websocket': self.websocket,
                'flow_id': self.client_id,
                'chat_id': self.chat_id
            })]

        # TODO zgq: 流式输出和 获取agent执行的每一个工具信息。写入chatmessages
        inputs = message.get('inputs', {})
        await self.add_message('human', json.dumps(inputs, ensure_ascii=False), 'question')

        await self.send_response('processing', 'start', '')
        if input_msg := inputs.get('input'):
            result = await self.gpts_agent.run(input_msg, async_callbacks)
            logger.debug(f'gpts agent {self.client_key} result: {result}')
            answer = ''
            for one in result[1:]:
                if isinstance(one, AIMessage):
                    answer += one.content
            await self.add_message('bot', answer, 'answer')
            await self.send_response('answer', 'start', '')
            await self.send_response('answer', 'end', answer)
        await self.send_response('processing', 'end', '')
