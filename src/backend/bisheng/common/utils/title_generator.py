"""Conversation title generator utility.

Provides async and sync functions for generating conversation titles using LLM.
"""

import asyncio
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from bisheng.common.utils.message_content import extract_message_text
from bisheng.core.prompts.manager import get_prompt_manager, get_prompt_manager_sync

logger = logging.getLogger(__name__)

# Last resort when neither model output nor the user's question has visible text.
DEFAULT_TITLE = "New Chat"
TITLE_GENERATION_TIMEOUT_S = 25.0
_TITLE_MAX_CHARS = 50


def normalize_conversation_title(content: str, question: str) -> str:
    """Exclude inline reasoning, including a truncated reasoning-only response."""
    title = re.sub(r"<think\b[^>]*>.*?(?:</think\s*>|$)", "", content, flags=re.IGNORECASE | re.DOTALL)
    title = re.sub(r"</?think\s*>?", "", title, flags=re.IGNORECASE).strip()
    if not title:
        title = (question or "").strip()
    return title.splitlines()[0].strip()[:_TITLE_MAX_CHARS] if title else DEFAULT_TITLE


def _thinking_off_kwargs(llm: BaseChatModel) -> dict:
    """Ask for the title without thinking.

    A title is a few words; a thinking model otherwise spends hundreds of
    reasoning tokens first. Measured 2026-11-09 on a production DeepSeek V4 under
    vLLM: 12s / 431 tokens with thinking, 0.6s / 4 tokens without, same title —
    and under task-mode load the thinking call ran past the title timeout.
    """
    getter = getattr(llm, "thinking_off_kwargs", None)
    return getter() if callable(getter) else {}


async def ainvoke_without_thinking(llm: BaseChatModel, messages: list):
    kwargs = _thinking_off_kwargs(llm)
    if kwargs:
        try:
            return await llm.ainvoke(messages, **kwargs)
        except Exception:
            # A server behind a generic provider type may reject the switch;
            # naming still works with the model's defaults, just slower.
            logger.warning("Title request with thinking off failed; retrying with provider defaults", exc_info=True)
    return await llm.ainvoke(messages)


def invoke_without_thinking(llm: BaseChatModel, messages: list):
    kwargs = _thinking_off_kwargs(llm)
    if kwargs:
        try:
            return llm.invoke(messages, **kwargs)
        except Exception:
            logger.warning("Title request with thinking off failed; retrying with provider defaults", exc_info=True)
    return llm.invoke(messages)


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
        Clean title, or a question-derived title if generation fails.
    """
    try:
        prompt_loader = await get_prompt_manager()
        prompt_obj = prompt_loader.render_prompt(
            "gen_title",
            "conversation_title",
            human=question or "",
        )

        messages = [HumanMessage(content=prompt_obj.prompt)]

        response = await asyncio.wait_for(ainvoke_without_thinking(llm, messages), timeout=TITLE_GENERATION_TIMEOUT_S)
        return normalize_conversation_title(extract_message_text(response), question)
    except Exception:
        # Naming is non-critical to the reply; retain the question and log the failure.
        logger.exception("Failed to generate conversation title")
        return normalize_conversation_title("", question)


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
        Clean title, or a question-derived title if generation fails.
    """
    try:
        prompt_loader = get_prompt_manager_sync()
        prompt_obj = prompt_loader.render_prompt(
            "gen_title",
            "conversation_title",
            human=question or "",
        )

        messages = [HumanMessage(content=prompt_obj.prompt)]

        response = invoke_without_thinking(llm, messages)
        return normalize_conversation_title(extract_message_text(response), question)
    except Exception:
        # Naming is non-critical to the reply; retain the question and log the failure.
        logger.exception("Failed to generate conversation title")
        return normalize_conversation_title("", question)
