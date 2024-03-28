from typing import Dict

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import WorkType
from bisheng.database.models.assistant import AssistantDao
from fastapi import WebSocket


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

    async def handle_gpts_message(self, message: Dict[any, any]):
        # 处理智能助手业务
        if self.chat_id and self.gpts_agent is None:
            # 会话业务agent通过数据库数据固定生成,不用每次变化
            assistant = AssistantDao.get_one_assistant(int(self.client_id))
            self.gpts_agent = AssistantAgent(assistant, self.chat_id)
        else:
            # 每次都从数据库获取重新构造一个agent
            # TODO zgq：后续可以和前端约定参数，决定是否要重新初始化agent
            assistant = AssistantDao.get_one_assistant(int(self.client_id))
            self.gpts_agent = AssistantAgent(assistant, self.chat_id)

        # TODO zgq: 流式输出和 获取agent执行的每一个工具信息
        inputs = message.get('inputs', {})
        if input_msg := inputs.get('input'):
            self.gpts_agent.run(input_msg)
        await self.send_json(ChatResponse(
            category='processing',
            type='end',
            is_bot=True,
            message='',
            user_id=self.user_id,
            intermediate_steps=''))
