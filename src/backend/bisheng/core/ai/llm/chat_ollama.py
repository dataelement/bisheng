import re
from typing import Iterator, Optional, Any, List, AsyncIterator, ClassVar

from langchain_core.messages import BaseMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_ollama import ChatOllama
from langchain_ollama.chat_models import (
    _get_usage_metadata_from_generation_info,
    _get_tool_calls_from_response
)
from loguru import logger


class CustomChatOllamaWithReasoning(ChatOllama):
    """
    Custom ChatOllama class that supports processing reasoning content in <think> tags.

    During streaming output:
    - Content outside <think> tags: content has value, reasoning_content is null
    - Content inside <think> tags: reasoning_content has value, content is empty string
    - <think> and </think> tags themselves are filtered out

    Attributes:
        in_think: Tracks whether we're currently inside <think> tags during streaming
    """

    # Class constants - marked as ClassVar to avoid Pydantic field detection
    THINK_START_TAG: ClassVar[str] = "<think>"
    THINK_END_TAG: ClassVar[str] = "</think>"
    THINK_PATTERN: ClassVar[re.Pattern] = re.compile(r'<think>(.*?)</think>', re.DOTALL)
    THINK_REMOVAL_PATTERN: ClassVar[re.Pattern] = re.compile(r'<think>.*?</think>\s*', re.DOTALL)

    def __init__(self, **kwargs):
        """Initialize with reasoning always enabled."""
        super().__init__(**kwargs)

    def _iterate_over_stream(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Handle the original Ollama stream processing logic."""
        reasoning = kwargs.get("reasoning", self.reasoning)
        in_think = False

        for stream_resp in self._create_chat_stream(messages, stop, **kwargs):
            if isinstance(stream_resp, str):
                continue

            content = self._extract_content_from_response(stream_resp)

            # Handle think tags
            if content == self.THINK_START_TAG:
                in_think = True
                continue
            elif content == self.THINK_END_TAG:
                in_think = False
                continue

            # Skip empty load responses
            if self._is_empty_load_response(stream_resp, content):
                continue

            generation_info = self._build_generation_info(stream_resp)
            additional_kwargs = self._build_additional_kwargs(reasoning, content, in_think)

            # Clear content when inside think tags
            if in_think and content:
                additional_kwargs["reasoning_content"] = content
                content = ""

            chunk = self._create_chat_generation_chunk(
                content, additional_kwargs, stream_resp, generation_info
            )
            yield chunk

    async def _aiterate_over_stream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        reasoning = kwargs.get("reasoning", self.reasoning)
        in_think = False
        async for stream_resp in self._acreate_chat_stream(messages, stop, **kwargs):
            if isinstance(stream_resp, str):
                continue

            content = self._extract_content_from_response(stream_resp)

            # Handle think tags
            if content == self.THINK_START_TAG:
                in_think = True
                continue
            elif content == self.THINK_END_TAG:
                in_think = False
                continue

            # Skip empty load responses
            if self._is_empty_load_response(stream_resp, content):
                continue

            generation_info = self._build_generation_info(stream_resp)
            additional_kwargs = self._build_additional_kwargs(reasoning, content, in_think)

            # Clear content when inside think tags
            if in_think and content:
                additional_kwargs["reasoning_content"] = content
                content = ""

            chunk = self._create_chat_generation_chunk(
                content, additional_kwargs, stream_resp, generation_info
            )
            yield chunk

    # Helper methods for better code organization

    def _extract_content_from_response(self, stream_resp: dict) -> str:
        """Extract content from stream response safely."""
        try:
            return stream_resp.get("message", {}).get("content", "")
        except (AttributeError, TypeError):
            return ""

    def _is_empty_load_response(self, stream_resp: dict, content: str) -> bool:
        """Check if response is an empty load response that should be skipped."""
        is_empty_load = (
                stream_resp.get("done") is True
                and stream_resp.get("done_reason") == "load"
                and not content.strip()
        )

        if is_empty_load:
            logger.warning(
                "Ollama returned empty response with done_reason='load'. "
                "This typically indicates the model was loaded but no content "
                "was generated. Skipping this response."
            )

        return is_empty_load

    def _build_generation_info(self, stream_resp: dict) -> Optional[dict]:
        """Build generation info from stream response."""
        if not stream_resp.get("done"):
            return None

        generation_info = dict(stream_resp)
        if "model" in generation_info:
            generation_info["model_name"] = generation_info["model"]
        generation_info.pop("message", None)
        return generation_info

    def _build_additional_kwargs(self, reasoning: bool, content: str, in_think: bool) -> dict:
        """Build additional kwargs for chunk."""
        additional_kwargs = {}
        if reasoning and in_think and content:
            additional_kwargs["reasoning_content"] = content
        return additional_kwargs

    def _create_chat_generation_chunk(
            self,
            content: str,
            additional_kwargs: dict,
            stream_resp: dict,
            generation_info: Optional[dict]
    ) -> ChatGenerationChunk:
        """Create a ChatGenerationChunk with proper metadata."""
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content=content,
                additional_kwargs=additional_kwargs,
                usage_metadata=_get_usage_metadata_from_generation_info(stream_resp),
                tool_calls=_get_tool_calls_from_response(stream_resp),
            ),
            generation_info=generation_info,
        )
