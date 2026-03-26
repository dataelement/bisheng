"""Conversation title generator utility.

Provides async and sync functions for generating conversation titles using LLM.
"""

import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from bisheng.core.prompts.manager import get_prompt_manager, get_prompt_manager_sync

logger = logging.getLogger(__name__)

# Default title when LLM fails or returns empty
DEFAULT_TITLE = "New Conversation"


async def generate_conversation_title_async(
        question: str,
        llm: BaseChatModel,
        answer: Optional[str] = None,
) -> str:
    """Generate a conversation title asynchronously.

    Args:
        question: The user's question content.
        llm: The BaseChatModel instance to use for generation.
        answer: Optional assistant's answer content.

    Returns:
        Generated title string, or default title if generation fails.
    """
    try:
        prompt_loader = await get_prompt_manager()
        prompt_obj = prompt_loader.render_prompt(
            "gen_title",
            "conversation_title",
            QUESTION=question or "",
            ANSWER=answer or "",
        )

        messages = [
            SystemMessage(content=prompt_obj.prompt.system),
            HumanMessage(content=prompt_obj.prompt.user),
        ]

        response = await llm.ainvoke(messages)
        title = response.content.strip() if response.content else ""

        return title if title else DEFAULT_TITLE
    except Exception as e:
        logger.error(f"Failed to generate conversation title: {e}")
        return DEFAULT_TITLE


def generate_conversation_title_sync(
        question: str,
        llm: BaseChatModel,
        answer: Optional[str] = None,
) -> str:
    """Generate a conversation title synchronously.

    Args:
        question: The user's question content.
        llm: The BaseChatModel instance to use for generation.
        answer: Optional assistant's answer content.

    Returns:
        Generated title string, or default title if generation fails.
    """
    try:
        prompt_loader = get_prompt_manager_sync()
        prompt_obj = prompt_loader.render_prompt(
            "gen_title",
            "conversation_title",
            QUESTION=question or "",
            ANSWER=answer or "",
        )

        messages = [
            SystemMessage(content=prompt_obj.prompt.system),
            HumanMessage(content=prompt_obj.prompt.user),
        ]

        response = llm.invoke(messages)
        title = response.content.strip() if response.content else ""

        return title if title else DEFAULT_TITLE
    except Exception as e:
        logger.error(f"Failed to generate conversation title: {e}")
        return DEFAULT_TITLE
