"""
Channel Article AI Assistant Chat Service

Encapsulates business logic for channel article AI assistant chat, including:
- Fetching article content
- Building conversation context
- Managing conversation sessions and message records
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from loguru import logger

from bisheng.api.services.workstation import WorkStationService
from bisheng.api.v1.schemas import SubscriptionConfig
from bisheng.channel.domain.schemas.channel_chat_schema import ChannelArticleChatRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService

# Article context prompt template
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.citation.domain.services.citation_prompt_helper import (
    annotate_article_with_citation,
    cache_citation_registry_items,
    filter_registry_items_by_text,
    save_message_citations,
    strip_unregistered_citation_markers,
)
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ArticleNotFoundError, ChannelChatConversationNotFoundError
from bisheng.common.image_view import ImageRegistry, annotate, run_react_vision_stream
from bisheng.database.constants import MessageCategory
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService

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
        cls, article_doc_id: str, user_id: int, article_title: str
    ) -> tuple[MessageSession, bool]:
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
            flow_ids=[article_doc_id], user_ids=[user_id], flow_type=[FlowType.CHANNEL_ARTICLE.value]
        )

        if sessions:
            logger.info(f"Found existing session for article {article_doc_id}, user {user_id}")
            return sessions[0], False

        # Create new session
        conversation_id = uuid4().hex
        await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=conversation_id,
                flow_id=article_doc_id,
                flow_name=f"Article Assistant: {article_title[:50]}",
                flow_type=FlowType.CHANNEL_ARTICLE.value,
                user_id=user_id,
            )
        )

        session = await MessageSessionDao.async_get_one(conversation_id)
        logger.info(f"Created new session {conversation_id} for article {article_doc_id}, user {user_id}")
        return session, True

    @classmethod
    async def _get_chat_config(cls, selected_model_id: int) -> tuple[int, SubscriptionConfig]:
        """
        Get chat configuration (model and prompts)

        Returns:
            tuple: (model_id, subscription_config)
        """
        # Get subscription configuration
        subscription_config = await WorkStationService.get_subscription_config()

        return selected_model_id, subscription_config

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
        logger.warning(f"Article content truncated from {len(content)} to {max_length} characters")
        return truncated

    @classmethod
    async def _resolve_workbench_visual(cls, model_id: int, tenant_id: int | None = None) -> bool:
        """Same WSModel.visual lookup as Linsight ``_resolve_model``."""
        workbench = await LLMService.get_workbench_llm(tenant_id=tenant_id)
        return any(
            str(entry.id) == str(model_id) and bool(getattr(entry, "visual", False))
            for entry in (workbench.models or [])
        )

    @staticmethod
    def _apply_image_anchors(article_content: str, visual: bool) -> tuple[str, ImageRegistry]:
        registry = ImageRegistry()
        if not visual:
            return article_content, registry
        return annotate(article_content, registry), registry

    @classmethod
    async def stream_article_reply(
        cls,
        *,
        llm: Any,
        article_content: str,
        question: str,
        system_prompt: str,
        user_prompt_template: str,
        history_messages: list[BaseMessage],
        model_id: int,
        max_chunk_size: int,
        tenant_id: int | None = None,
    ) -> AsyncIterator[Any]:
        """Truncate, annotate markdown images, then stream via the vision tool loop."""
        article_content = cls._truncate_article_content(article_content, max_chunk_size)
        visual = await cls._resolve_workbench_visual(model_id, tenant_id)
        article_content, registry = cls._apply_image_anchors(article_content, visual)
        user_prompt = user_prompt_template.format(article_content=article_content, question=question)
        inputs = [SystemMessage(content=system_prompt), *history_messages, HumanMessage(content=user_prompt)]
        async for chunk in run_react_vision_stream(llm, inputs, registry, visual=visual):
            yield chunk

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

    ARTICLE_SNIPPET_LENGTH = 200

    @classmethod
    async def register_article_citation(cls, article) -> tuple[str, list[CitationRegistryItemSchema]]:
        """Register the article being discussed as a citation source.

        One article is one source: channel QA hands the model the whole article
        rather than retrieving chunks, so there is nothing finer to address and
        the locator is the article's own doc id (never a synthesised chunk id).

        Returns the citation key for the prompt and the items to persist later.
        Tracing is an add-on to answering, so any failure here degrades to
        ("", []) and the turn proceeds without a badge.
        """
        try:
            content = getattr(article, "content", "") or ""
            citation_key, items = annotate_article_with_citation(
                article_doc_id=article.doc_id,
                title=getattr(article, "title", None),
                snippet=content[: cls.ARTICLE_SNIPPET_LENGTH] or None,
                source_url=getattr(article, "source_url", None),
                source_type=getattr(article, "source_type", None),
            )
            await cache_citation_registry_items(items)
            return citation_key, items
        except Exception as exc:
            logger.warning(f"[channel_citation] register failed, answering without a source: {exc}")
            return "", []

    @classmethod
    def decorate_article_content(cls, content: str, citation_key: str) -> str:
        """Attach the source id to the article text handed to the model.

        Done on the content rather than the prompt template because the template
        is admin-configurable — decorating the content means the id survives
        whatever wording an admin chooses.
        """
        if not citation_key:
            return content
        return f"{content}\n\ncitation_key: {citation_key}"

    @classmethod
    def scrub_article_answer(
        cls,
        answer: str,
        items: list[CitationRegistryItemSchema],
    ) -> tuple[str, list[CitationRegistryItemSchema]]:
        """Decide what to keep, and clean the answer, BEFORE it is stored.

        Strict on purpose: unlike the retrieval entries, this path does not fall
        back to storing every registered item when the answer cites nothing. An
        article source is registered on every turn, so that fallback would leave
        a stored source behind each uncited turn with no badge to click.

        Markers the registry cannot back are removed here too — a hallucinated
        id would otherwise render as a badge whose lookup 404s, which reads as a
        system fault rather than the model inventing an id.
        """
        try:
            cited = filter_registry_items_by_text(items, answer)
            return strip_unregistered_citation_markers(answer, cited), cited
        except Exception as exc:
            logger.warning(f"[channel_citation] scrub failed, storing the answer unchanged: {exc}")
            return answer, []

    @classmethod
    async def save_article_citations(
        cls,
        items: list[CitationRegistryItemSchema],
        message_id: int | None,
        chat_id: str | None = None,
        flow_id: str | None = None,
    ) -> None:
        """Bind the cited sources to the stored answer. Never fails the turn.

        Idempotent by way of the unique citation id on message_citation, so a
        replayed turn does not duplicate rows.
        """
        if not items:
            return
        try:
            await save_message_citations(message_id=message_id, items=items, chat_id=chat_id, flow_id=flow_id)
        except Exception as exc:
            logger.warning(f"[channel_citation] persist failed, answer already stored: {exc}")

    @classmethod
    def build_article_context_prompt(cls, title: str, content: str, question: str, citation_key: str = "") -> str:
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
            content=cls.decorate_article_content(content, citation_key),
            question=question,
        )

    @classmethod
    async def initialize_chat(cls, data: ChannelArticleChatRequest, login_user: UserPayload, article_title: str):
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
            article_doc_id=data.article_doc_id, user_id=login_user.user_id, article_title=article_title
        )

        # Create user message record

        # Get chat configuration
        model_id, subscription_config = await cls._get_chat_config(data.model_id)

        # Get LLM instance
        bishengllm = await LLMService.get_bisheng_llm(
            model_id=model_id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name="channel_article_chat",
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=login_user.user_id,
        )

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
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id, ["question", "answer"], size)
        for one in messages:
            try:
                extra = json.loads(one.extra) if one.extra else {}
            except json.JSONDecodeError:
                extra = {}
            content = extra.get("prompt", one.message)
            if one.category == MessageCategory.QUESTION.value:
                chat_history.append(HumanMessage(content=content))
            elif one.category == MessageCategory.ANSWER.value:
                chat_history.append(AIMessage(content=content))
        logger.info(f"loaded {len(chat_history)} chat history for channel article chat_id {chat_id}")
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
            flow_ids=[article_doc_id], user_ids=[login_user.user_id], flow_type=[FlowType.CHANNEL_ARTICLE.value]
        )

        if not sessions:
            return []

        conversation = sessions[0]
        # Permission already verified by user_ids filter above
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id=conversation.chat_id, limit=1000)

        return messages

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
            flow_ids=[article_doc_id], user_ids=[login_user.user_id], flow_type=[FlowType.CHANNEL_ARTICLE.value]
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
