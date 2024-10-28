import json
from typing import Dict, Callable
from uuid import UUID, uuid4
from queue import Queue

from loguru import logger
from langchain_core.messages import AIMessage, HumanMessage
from fastapi import WebSocket, status, Request

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler
from bisheng.api.v1.schemas import ChatMessage, ChatResponse
from bisheng.chat.types import IgnoreException, WorkType
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.settings import settings
from bisheng.api.utils import get_request_ip
from bisheng.utils.threadpool import ThreadPoolManager, thread_pool


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

        # 业务自定义参数
        self.gpts_agent: AssistantAgent | None = None
        self.gpts_async_callback = None
        self.chat_history = []
        # 和模型对话时传入的 完整的历史对话轮数
        self.latest_history_num = 5
        self.gpts_conf = settings.get_from_db('gpts')
        # 异步任务列表
        self.task_ids = []
        # 流式输出的队列，用来接受流式输出的内容，每次处理新的question时都清空
        self.stream_queue = Queue()

    async def send_message(self, message: str):
        await self.websocket.send_text(message)

    async def send_json(self, message: ChatMessage):
        await self.websocket.send_json(message.dict())

    async def handle_message(self, message: Dict[any, any]):
        trace_id = uuid4().hex
        logger.info(f'client_id={self.client_key} trace_id={trace_id} message={message}')
        with logger.contextualize(trace_id=trace_id):
            # 处理客户端发过来的信息, 提交到线程池内执行
            if self.work_type == WorkType.GPTS:
                thread_pool.submit(trace_id,
                                   self.wrapper_task,
                                   trace_id,
                                   self.handle_gpts_message,
                                   message,
                                   trace_id=trace_id)
                # await self.handle_gpts_message(message)

    async def wrapper_task(self, task_id: str, fn: Callable, *args, **kwargs):
        # 包装处理函数为异步任务
        self.task_ids.append(task_id)
        try:
            # 执行处理函数
            await fn(*args, **kwargs)
        except Exception as e:
            logger.exception("handle message error")
        finally:
            # 执行完成后将任务id从列表移除
            self.task_ids.remove(task_id)

    async def add_message(self, msg_type: str, message: str, category: str, remark: str = ''):
        self.chat_history.append({
            'category': category,
            'message': message,
            'remark': remark
        })
        if not self.chat_id:
            # debug模式无需保存历史
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
        # 记录审计日志, 是新建会话
        if len(self.chat_history) <= 1:
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
            logger.exception("get assistant info error")
            await self.websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
            raise IgnoreException(f'get assistant info error: {str(e)}')
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
            logger.exception("agent init error")
            raise Exception(f'agent init error: {str(e)}')

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
                    'category': one.category,
                    'remark': one.remark
                })

    async def get_latest_history(self):
        # 需要将无效的历史消息剔除，只包含一问一答的完整会话记录
        tmp = []
        find_i = 0
        is_answer = True
        # 从聊天历史里获取
        for i in range(len(self.chat_history) - 1, -1, -1):
            one_item = self.chat_history[i]
            if find_i >= self.latest_history_num:
                break
            # 不包含中断的答案
            if one_item['category'] == 'answer' and one_item.get('remark') != 'break_answer' and is_answer:
                tmp.insert(0, AIMessage(content=one_item['message']))
                is_answer = False
            elif one_item['category'] == 'question' and not is_answer:
                tmp.insert(0, HumanMessage(content=json.loads(one_item['message'])['input']))
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
            'user_id': self.user_id,
            'stream_queue': self.stream_queue,
        })]
        self.gpts_async_callback = async_callbacks

    async def stop_handle_message(self, message: Dict[any, any]):
        # 中止流式输出, 因为最新的任务id是中止任务的id，不能取消自己
        logger.info(f'need stop agent, client_key: {self.client_key}, message: {message}')

        # 中止之前的处理函数
        thread_pool.cancel_task(self.task_ids[:-1])

        # 将流式输出的内容写到数据库内
        answer = ''
        while not self.stream_queue.empty():
            msg = self.stream_queue.get()
            answer += msg

        # 有流式输出内容的话，记录流式输出内容到数据库
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
            # 清空流式队列，防止把上一次的回答，污染本次回答
            await self.clear_stream_queue()
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

            # todo: 后续优化代码解释器的实现方案，保证输出的文件可以公开访问 ugly solve
            # 获取minio的share地址，把share域名去掉, 为毕昇的部署方案特殊处理下
            for one in self.gpts_agent.tools:
                if one.name == "bisheng_code_interpreter":
                    minio_share = settings.get_knowledge().get('minio', {}).get('MINIO_SHAREPOIN', '')
                    answer = answer.replace(f"http://{minio_share}", "")
            answer_end_type = 'end'
            # 如果是流式的llm则用end_cover结束, 覆盖之前流式的输出
            if getattr(self.gpts_agent.llm, 'streaming', False):
                answer_end_type = 'end_cover'

            res = await self.add_message('bot', answer, 'answer')
            await self.send_response('answer', 'start', '')
            await self.send_response('answer', answer_end_type, answer, message_id=res.id if res else None)
            logger.info(f'gptsAgentOver assistant_id:{self.client_id} chat_id:{self.chat_id} question:{input_msg}')
            logger.info(f'gptsAgentOver assistant_id:{self.client_id} chat_id:{self.chat_id} answer:{answer}')
        except Exception as e:
            logger.exception('handle gpts message error: ')
            await self.send_response('system', 'start', '')
            await self.send_response('system', 'end', 'Error: ' + str(e))
        finally:
            await self.send_response('processing', 'close', '')
