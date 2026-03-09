"""
频道文章AI助手对话 Service

封装频道文章AI助手对话的业务逻辑，包括：
- 获取文章内容
- 构建对话上下文
- 管理对话会话和消息记录
"""
import json
from typing import Optional, Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from bisheng.api.services.workstation import WorkstationMessage, WorkstationConversation
from bisheng.channel.domain.schemas.channel_chat_schema import ChannelArticleChatRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ArticleNotFoundError, ChannelChatConversationNotFoundError
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService


# 文章上下文提示模版
ARTICLE_CONTEXT_PROMPT = (
    "你是一个专业的AI助手，请基于以下文章内容来回答用户的问题。\n\n"
    "## 文章标题\n{title}\n\n"
    "## 文章内容\n{content}\n\n"
    "---\n"
    "请根据上述文章内容回答以下问题：\n{question}"
)


class ChannelChatService:
    """频道文章AI助手对话 Service"""

    @classmethod
    async def get_article_content(cls, article_es_service: ArticleEsService, doc_id: str):
        """
        通过 ArticleEsService 获取文章内容

        Args:
            article_es_service: ES文章服务实例
            doc_id: ES文章文档ID

        Returns:
            ArticleSearchResultItem 文章信息

        Raises:
            ArticleNotFoundError: 文章不存在
        """
        article = await article_es_service.get_article(doc_id)
        if not article:
            raise ArticleNotFoundError()
        return article

    @classmethod
    def build_article_context_prompt(cls, title: str, content: str, question: str) -> str:
        """
        构建文章上下文提示

        Args:
            title: 文章标题
            content: 文章纯文本内容
            question: 用户问题

        Returns:
            str: 完整的提示文本
        """
        return ARTICLE_CONTEXT_PROMPT.format(
            title=title,
            content=content,
            question=question
        )

    @classmethod
    async def initialize_chat(cls, data: ChannelArticleChatRequest,
                              login_user: UserPayload,
                              article_title: str):
        """
        初始化对话会话，参考 workstation._initialize_chat

        Args:
            data: 对话请求数据
            login_user: 登录用户信息
            article_title: 文章标题（用于会话名称）

        Returns:
            tuple: (conversation, message, bishengllm, is_new_conversation)
        """
        conversationId = data.conversationId
        is_new_conversation = False

        if not conversationId:
            is_new_conversation = True
            conversationId = uuid4().hex
            await MessageSessionDao.async_insert_one(
                MessageSession(
                    chat_id=conversationId,
                    flow_id=data.article_doc_id,
                    flow_name=f'文章助手: {article_title[:50]}',
                    flow_type=FlowType.CHANNEL_ARTICLE.value,
                    user_id=login_user.user_id,
                ))

        conversation = await MessageSessionDao.async_get_one(conversationId)
        if conversation is None:
            raise ChannelChatConversationNotFoundError()

        # 创建用户消息记录
        message = await ChatMessageDao.ainsert_one(
            ChatMessage(
                user_id=login_user.user_id,
                chat_id=conversationId,
                flow_id=data.article_doc_id,
                type='human',
                is_bot=False,
                sender='User',
                extra=json.dumps({'parentMessageId': data.parentMessageId}),
                message=data.text,
                category='question',
                source=0,
            ))

        # 获取 LLM 实例
        bishengllm = await LLMService.get_bisheng_llm(
            model_id=data.model,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name='channel_article_chat',
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=login_user.user_id)

        return conversation, message, bishengllm, is_new_conversation

    @classmethod
    async def get_chat_history(cls, chat_id: str, size: int = 8):
        """
        获取对话历史，构建 LangChain 消息列表

        Args:
            chat_id: 会话ID
            size: 获取的历史消息数量

        Returns:
            list: LangChain 消息列表
        """
        chat_history = []
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id, ['question', 'answer'], size)
        for one in messages:
            extra = json.loads(one.extra) or {}
            content = extra.get('prompt', one.message)
            if one.category == MessageCategory.QUESTION.value:
                chat_history.append(HumanMessage(content=content))
            elif one.category == MessageCategory.ANSWER.value:
                chat_history.append(AIMessage(content=content))
        logger.info(f'loaded {len(chat_history)} chat history for channel article chat_id {chat_id}')
        return chat_history

    @classmethod
    async def get_chat_messages(cls, conversation_id: str, login_user: UserPayload):
        """
        查询对话历史消息列表

        Args:
            conversation_id: 会话ID
            login_user: 登录用户信息

        Returns:
            list: WorkstationMessage 列表
        """
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversation_id, limit=1000)
        if messages:
            if login_user.user_id != messages[0].user_id:
                return None  # 无权限
            return [await WorkstationMessage.from_chat_message(message) for message in messages]
        return []

    @classmethod
    async def clear_chat(cls, conversation_id: str, login_user: UserPayload) -> bool:
        """
        清空对话内容

        Args:
            conversation_id: 会话ID
            login_user: 登录用户信息

        Returns:
            bool: 是否清空成功
        """
        # 验证会话存在且属于当前用户
        conversation = await MessageSessionDao.async_get_one(conversation_id)
        if not conversation:
            raise ChannelChatConversationNotFoundError()
        if conversation.user_id != login_user.user_id:
            return False

        # 删除对话消息
        ChatMessageDao.delete_by_user_chat_id(login_user.user_id, conversation_id)
        # 标记会话为已删除
        await MessageSessionDao.delete_session(conversation_id)
        return True
