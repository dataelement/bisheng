import json
import os
import time
from typing import Dict
from uuid import UUID, uuid4

from loguru import logger
from langchain_core.messages import AIMessage, HumanMessage
from langchain.tools.render import format_tool_to_openai_tool
from fastapi import WebSocket, status

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import IgnoreException, WorkType
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.settings import settings


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
        self.gpts_async_callback = None
        self.chat_history = []
        # 和模型对话时传入的 完整的历史对话轮数
        self.latest_history_num = 5
        self.gpts_conf = settings.get_from_db('gpts')

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage):
        await self.websocket.send_json(message.dict())

    async def handle_message(self, message: Dict[any, any]):
        trace_id = uuid4().hex
        with logger.contextualize(trace_id=trace_id):
            # 处理客户端发过来的信息
            if self.work_type == WorkType.GPTS:
                await self.handle_gpts_message(message)

    async def add_message(self, msg_type: str, message: str, category: str):
        self.chat_history.append({
            'category': category,
            'message': message
        })
        if not self.chat_id:
            # debug模式无需保存历史
            return
        is_bot = 0 if msg_type == 'human' else 1
        return ChatMessageDao.insert_one(ChatMessageModel(
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
            # 处理智能助手业务
            if self.chat_id and self.gpts_agent is None:
                # 会话业务agent通过数据库数据固定生成,不用每次变化
                assistant = AssistantDao.get_one_assistant(UUID(self.client_id))
                if not assistant:
                    raise IgnoreException('该助手已被删除')
                    # 判断下agent是否上线
                if assistant.status != AssistantStatus.ONLINE.value:
                    raise IgnoreException('当前助手未上线，无法直接对话')
            elif not self.chat_id:
                # 调试界面没测都重新生成
                assistant = AssistantDao.get_one_assistant(UUID(self.client_id))
                if not assistant:
                    raise IgnoreException('该助手已被删除')
        except IgnoreException as e:
            await self.websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
            raise IgnoreException('get assistant info error')
        try:
            if self.chat_id and self.gpts_agent is None:
                # 会话业务agent通过数据库数据固定生成,不用每次变化
                self.gpts_agent = AssistantAgent(assistant, self.chat_id)
                await self.gpts_agent.init_assistant(self.gpts_async_callback)
            elif not self.chat_id:
                # 调试界面每次都重新生成
                self.gpts_agent = AssistantAgent(assistant, self.chat_id)
                await self.gpts_agent.init_assistant(self.gpts_async_callback)
        except Exception as e:
            await self.websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=f'agent init error {str(e)}')
            raise Exception('agent init error')

    async def init_chat_history(self):
        # 初始化历史记录，不为空则不用重新初始化
        if len(self.chat_history) > 0:
            return
        # 从数据库加载历史会话
        if self.chat_id:
            res = ChatMessageDao.get_messages_by_chat_id(self.chat_id, ['question', 'answer'],
                                                         self.latest_history_num * 4)
            for one in res:
                self.chat_history.append({
                    'message': one.message,
                    'category': one.category
                })

    async def get_latest_history(self):
        # 需要将无效的历史消息剔除，只包含一问一答的完整会话记录
        tmp = []
        find_i = 0
        is_answer = True
        # 从聊天历史里获取
        for i in range(len(self.chat_history) - 1, -1, -1):
            if find_i >= self.latest_history_num:
                break
            if self.chat_history[i]['category'] == 'answer' and is_answer:
                tmp.insert(0, AIMessage(content=self.chat_history[i]['message']))
                is_answer = False
            elif self.chat_history[i]['category'] == 'question' and not is_answer:
                tmp.insert(0, HumanMessage(content=json.loads(self.chat_history[i]['message'])['input']))
                is_answer = True
                find_i += 1

        return tmp

    async def init_gpts_callback(self):
        if self.gpts_async_callback is not None:
            return
        async_callbacks = [AsyncGptsDebugCallbackHandler(**{
            'websocket': self.websocket,
            'flow_id': self.client_id,
            'chat_id': self.chat_id,
            'user_id': self.user_id
        })]
        self.gpts_async_callback = async_callbacks

    async def handle_gpts_message(self, message: Dict[any, any]):
        if not message:
            return
        logger.debug(f'receive client message, client_key: {self.client_key} message: {message}')

        inputs = message.get('inputs', {})
        input_msg = inputs.get('input')
        if not input_msg:
            # 需要切换会话
            logger.debug(f'need switch agent, client_key: {self.client_key} inputs: {inputs}')
            self.client_id = inputs.get('data').get('id')
            self.chat_id = inputs.get('data').get('chatId')
            self.gpts_agent = None
            self.gpts_async_callback = None
            self.chat_history = []
            await self.init_gpts_agent()
            return

        # 初始化agent
        await self.init_gpts_agent()

        await self.send_response('processing', 'begin', '')

        try:
            # 将用户问题写入到数据库
            await self.add_message('human', json.dumps(inputs, ensure_ascii=False), 'question')

            # 获取回话历史
            chat_history = await self.get_latest_history()
            # 调用agent获取结果
            result = await self.gpts_agent.run(input_msg, chat_history, self.gpts_async_callback)
            logger.debug(f'gpts agent {self.client_key} result: {result}')
            answer = ''
            for one in result:
                if isinstance(one, AIMessage):
                    answer += one.content

            # todo: 后续优化代码解释器的实现方案，保证输出的文件可以公开访问
            # 获取minio的share地址，把share域名去掉, 为毕昇的部署方案特殊处理下
            if gpts_tool_conf := self.gpts_conf.get('tools'):
                if bisheng_code_conf := gpts_tool_conf.get("bisheng_code_interpreter"):
                    answer = answer.replace(f"http://{bisheng_code_conf['minio']['MINIO_SHAREPOIN']}", "")

            res = await self.add_message('bot', answer, 'answer')
            await self.send_response('answer', 'start', '')
            await self.send_response('answer', 'end_cover', answer, message_id=res.id if res else None)
            logger.info(f'gptsAgentOver assistant_id:{self.client_id} chat_id:{self.chat_id} question:{input_msg}')
            logger.info(f'gptsAgentOver assistant_id:{self.client_id} chat_id:{self.chat_id} answer:{answer}')
        except Exception as e:
            logger.exception('handle gpts message error: ')
            await self.send_response('system', 'start', '')
            await self.send_response('system', 'end', 'Error: ' + str(e))
        finally:
            await self.send_response('processing', 'close', '')

        # 记录助手的聊天历史
        if os.getenv("BISHENG_RECORD_HISTORY"):
            try:
                os.makedirs("/app/data/history", exist_ok=True)
                with open(f"/app/data/history/{self.client_id}_{time.time()}.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "system": self.gpts_agent.assistant.prompt,
                        "message": self.chat_history,
                        "tools": [format_tool_to_openai_tool(t) for t in self.gpts_agent.tools]
                    }, f, ensure_ascii=False)
            except Exception as e:
                logger.error("record assistant history error: ", e)
