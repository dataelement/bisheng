"""Conversation title generator utility.

Provides async and sync functions for generating conversation titles using LLM.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from bisheng.core.prompts.manager import get_prompt_manager, get_prompt_manager_sync

logger = logging.getLogger(__name__)

# Default title when LLM fails or returns empty
DEFAULT_TITLE = "New Chat"


async def generate_conversation_title_async(
        question: str,
        llm: BaseChatModel,
) -> str:
    """Generate a conversation title asynchronously, from the QUESTION alone.

    The assistant's answer used to be fed in as well, which forced the whole
    title step to wait for the round to finish. The question already carries the
    topic, so dropping the answer lets a title be produced as soon as the user
    submits — and removes a dependency on a reply that may never arrive.

    Args:
        question: The user's question content.
        llm: The BaseChatModel instance to use for generation.

    Returns:
        Generated title string, or default title if generation fails.
    """
    try:
        prompt_loader = await get_prompt_manager()
        prompt_obj = prompt_loader.render_prompt(
            "gen_title",
            "conversation_title",
            human=question or "",
        )

        messages = [HumanMessage(content=prompt_obj.prompt)]

        response = await llm.ainvoke(messages)
        title = response.content.strip() if response.content else ""

        return title if title else DEFAULT_TITLE
    except Exception as e:
        logger.error(f"Failed to generate conversation title: {e}")
        return DEFAULT_TITLE


def generate_conversation_title_sync(
        question: str,
        llm: BaseChatModel,
) -> str:
    """Generate a conversation title synchronously, from the QUESTION alone.

    See ``generate_conversation_title_async`` for why the answer is not used.

    Args:
        question: The user's question content.
        llm: The BaseChatModel instance to use for generation.

    Returns:
        Generated title string, or default title if generation fails.
    """
    try:
        prompt_loader = get_prompt_manager_sync()
        prompt_obj = prompt_loader.render_prompt(
            "gen_title",
            "conversation_title",
            human=question or "",
        )

        messages = [HumanMessage(content=prompt_obj.prompt)]

        response = llm.invoke(messages)
        title = response.content.strip() if response.content else ""

        return title if title else DEFAULT_TITLE
    except Exception as e:
        logger.error(f"Failed to generate conversation title: {e}")
        return DEFAULT_TITLE
