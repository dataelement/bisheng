"""
Channel Article AI Assistant Chat Service

Encapsulates business logic for channel article AI assistant chat, including:
- Fetching article content
- Building conversation context
- Managing conversation sessions and message records
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


# Article context prompt template
ARTICLE_CONTEXT_PROMPT = (
    "You are a professional AI assistant, please answer user's questions based on the following article content.\n\n"
    "## Article Title\n{title}\n\n"
    "## Article Content\n{content}\n\n"
    "---\n"
    "Please answer the following question based on the article content above:\n{question}"
)


class ChannelChatService:
    """Channel Article AI Assistant Chat Service"""

    @classmethod
    async def get_article_content(cls, article_es_service: ArticleEsService, doc_id: str):
        """
        Fetch article content via ArticleEsService

        Args:
            article_es_service: ES article service instance
            doc_id: ES article document ID

        Returns:
            ArticleSearchResultItem article information

        Raises:
            ArticleNotFoundError: Article not found
        """
        article = await article_es_service.get_article(doc_id)
        if not article:
            raise ArticleNotFoundError()
        return article

    @classmethod
    def build_article_context_prompt(cls, title: str, content: str, question: str) -> str:
        """
        Build article context prompt

        Args:
            title: Article title
            content: Article plain text content
            question: User question

        Returns:
            str: Complete prompt text
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
        Initialize chat session, reference workstation._initialize_chat

        Args:
            data: Chat request data
            login_user: Logged-in user information
            article_title: Article title (used for session name)

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
                    flow_name=f'Article Assistant: {article_title[:50]}',
                    flow_type=FlowType.CHANNEL_ARTICLE.value,
                    user_id=login_user.user_id,
                ))

        conversation = await MessageSessionDao.async_get_one(conversationId)
        if conversation is None:
            raise ChannelChatConversationNotFoundError()

        # Create user message record
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

        # Get LLM instance
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
        Get chat history and build LangChain message list

        Args:
            chat_id: Session ID
            size: Number of history messages to fetch

        Returns:
            list: LangChain message list
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
        Query chat history message list

        Args:
            conversation_id: Session ID
            login_user: Logged-in user information

        Returns:
            list: WorkstationMessage list
        """
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversation_id, limit=1000)
        if messages:
            if login_user.user_id != messages[0].user_id:
                return None  # No permission
            return [await WorkstationMessage.from_chat_message(message) for message in messages]
        return []

    @classmethod
    async def clear_chat(cls, conversation_id: str, login_user: UserPayload) -> bool:
        """
        Clear chat content

        Args:
            conversation_id: Session ID
            login_user: Logged-in user information

        Returns:
            bool: Whether the clear operation succeeded
        """
        # Verify session exists and belongs to current user
        conversation = await MessageSessionDao.async_get_one(conversation_id)
        if not conversation:
            raise ChannelChatConversationNotFoundError()
        if conversation.user_id != login_user.user_id:
            return False

        # Delete chat messages
        ChatMessageDao.delete_by_user_chat_id(login_user.user_id, conversation_id)
        # Mark session as deleted
        await MessageSessionDao.delete_session(conversation_id)
        return True
