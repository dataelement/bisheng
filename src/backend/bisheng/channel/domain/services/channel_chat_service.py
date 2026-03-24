"""
Channel Article AI Assistant Chat Service

Encapsulates business logic for channel article AI assistant chat, including:
- Fetching article content
- Building conversation context
- Managing conversation sessions and message records
"""
import json
from typing import Tuple
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from bisheng.api.services.workstation import WorkstationMessage, WorkStationService
from bisheng.api.v1.schemas import SubscriptionConfig
from bisheng.channel.domain.schemas.channel_chat_schema import ChannelArticleChatRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import (
    ArticleNotFoundError, ChannelChatConversationNotFoundError, KnowledgeSpaceLLMNotConfiguredError
)
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.schemas import WorkbenchModelConfig

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
    async def _get_or_create_session(
            cls,
            article_doc_id: str,
            user_id: int,
            article_title: str
    ) -> Tuple[MessageSession, bool]:
        """
        Get or create session by article_doc_id + user_id (one-to-one mapping)

        Args:
            article_doc_id: Article document ID
            user_id: User ID
            article_title: Article title (used for session name)

        Returns:
            tuple: (MessageSession, is_new_session)
        """
        # Query existing session by flow_id (article_doc_id) and user_id
        sessions = await MessageSessionDao.afilter_session(
            flow_ids=[article_doc_id],
            user_ids=[user_id],
            flow_type=[FlowType.CHANNEL_ARTICLE.value]
        )

        if sessions:
            logger.info(f'Found existing session for article {article_doc_id}, user {user_id}')
            return sessions[0], False

        # Create new session
        conversation_id = uuid4().hex
        await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=conversation_id,
                flow_id=article_doc_id,
                flow_name=f'Article Assistant: {article_title[:50]}',
                flow_type=FlowType.CHANNEL_ARTICLE.value,
                user_id=user_id,
            )
        )

        session = await MessageSessionDao.async_get_one(conversation_id)
        logger.info(f'Created new session {conversation_id} for article {article_doc_id}, user {user_id}')
        return session, True

    @classmethod
    async def _get_chat_config(cls) -> Tuple[int, SubscriptionConfig]:
        """
        Get chat configuration (model and prompts)

        Returns:
            tuple: (model_id, subscription_config)

        Raises:
            KnowledgeSpaceLLMNotConfiguredError: If knowledge_space_llm not configured
        """
        # Get workbench LLM configuration
        workbench_llm: WorkbenchModelConfig = await LLMService.get_workbench_llm()

        if not workbench_llm or not workbench_llm.knowledge_space_llm:
            raise KnowledgeSpaceLLMNotConfiguredError()

        model_id = int(workbench_llm.knowledge_space_llm.id)

        # Get subscription configuration
        subscription_config = await WorkStationService.get_subscription_config()

        return model_id, subscription_config

    @classmethod
    def _truncate_article_content(cls, content: str, max_length: int) -> str:
        """
        Truncate article content to max_length

        Args:
            content: Article content
            max_length: Maximum length

        Returns:
            str: Truncated content
        """
        if len(content) <= max_length:
            return content

        truncated = content[:max_length]
        logger.warning(f'Article content truncated from {len(content)} to {max_length} characters')
        return truncated

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
        Initialize chat session (one-to-one: article + user = one session)

        Args:
            data: Chat request data
            login_user: Logged-in user information
            article_title: Article title (used for session name)

        Returns:
            tuple: (conversation, message, bishengllm, is_new_conversation)
        """
        # Get or create session (one-to-one mapping)
        conversation, is_new_conversation = await cls._get_or_create_session(
            article_doc_id=data.article_doc_id,
            user_id=login_user.user_id,
            article_title=article_title
        )

        # Create user message record

        # Get chat configuration
        model_id, subscription_config = await cls._get_chat_config()

        # Get LLM instance
        bishengllm = await LLMService.get_bisheng_llm(
            model_id=model_id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name='channel_article_chat',
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=login_user.user_id)

        return conversation, bishengllm, is_new_conversation, subscription_config

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
            try:
                extra = json.loads(one.extra) if one.extra else {}
            except json.JSONDecodeError:
                extra = {}
            content = extra.get('prompt', one.message)
            if one.category == MessageCategory.QUESTION.value:
                chat_history.append(HumanMessage(content=content))
            elif one.category == MessageCategory.ANSWER.value:
                chat_history.append(AIMessage(content=content))
        logger.info(f'loaded {len(chat_history)} chat history for channel article chat_id {chat_id}')
        return chat_history

    @classmethod
    async def get_chat_messages(cls, article_doc_id: str, login_user: UserPayload):
        """
        Query chat history message list by article_doc_id

        Args:
            article_doc_id: Article document ID
            login_user: Logged-in user information

        Returns:
            list: WorkstationMessage list or None if no permission
        """
        # Find session by article_doc_id + user_id
        sessions = await MessageSessionDao.afilter_session(
            flow_ids=[article_doc_id],
            user_ids=[login_user.user_id],
            flow_type=[FlowType.CHANNEL_ARTICLE.value]
        )

        if not sessions:
            return []

        conversation = sessions[0]
        # Permission already verified by user_ids filter above
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversation.chat_id, limit=1000)

        if not messages:
            return []

        return [await WorkstationMessage.from_chat_message(message) for message in messages]

    @classmethod
    async def clear_chat(cls, article_doc_id: str, login_user: UserPayload) -> bool:
        """
        Clear chat content by article_doc_id

        Args:
            article_doc_id: Article document ID
            login_user: Logged-in user information

        Returns:
            bool: Whether the clear operation succeeded

        Raises:
            ChannelChatConversationNotFoundError: If conversation not found
        """
        # Find session by article_doc_id + user_id
        sessions = await MessageSessionDao.afilter_session(
            flow_ids=[article_doc_id],
            user_ids=[login_user.user_id],
            flow_type=[FlowType.CHANNEL_ARTICLE.value]
        )

        if not sessions:
            raise ChannelChatConversationNotFoundError()

        conversation = sessions[0]
        # Permission already verified by user_ids filter above

        # Delete chat messages
        ChatMessageDao.delete_by_user_chat_id(login_user.user_id, conversation.chat_id)
        # Mark session as deleted
        await MessageSessionDao.delete_session(conversation.chat_id)
        return True
