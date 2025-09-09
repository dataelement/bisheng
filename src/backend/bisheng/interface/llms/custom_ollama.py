from typing import Iterator, Optional, Any, List, AsyncIterator, Tuple, ClassVar
from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, AIMessageChunk
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_ollama.chat_models import (
    _get_usage_metadata_from_generation_info,
    _get_tool_calls_from_response
)
from pydantic import Field
from loguru import logger
import re


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

    in_think: bool = Field(default=False, description="Track whether inside think tags")

    def __init__(self, **kwargs):
        """Initialize with reasoning always enabled."""
        kwargs["reasoning"] = True  # Always enable reasoning to get think content from Ollama
        super().__init__(**kwargs)

    def _iterate_over_stream(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Handle the original Ollama stream processing logic."""
        self._reset_think_state()
        reasoning = kwargs.get("reasoning", self.reasoning)

        for stream_resp in self._create_chat_stream(messages, stop, **kwargs):
            if isinstance(stream_resp, str):
                continue

            content = self._extract_content_from_response(stream_resp)

            # Handle think tags
            if content == self.THINK_START_TAG:
                self.in_think = True
                continue
            elif content == self.THINK_END_TAG:
                self.in_think = False
                continue

            # Skip empty load responses
            if self._is_empty_load_response(stream_resp, content):
                continue

            generation_info = self._build_generation_info(stream_resp)
            additional_kwargs = self._build_additional_kwargs(reasoning, content)

            # Clear content when inside think tags
            if reasoning and self.in_think and content:
                additional_kwargs["reasoning_content"] = content
                content = ""

            chunk = self._create_chat_generation_chunk(
                content, additional_kwargs, stream_resp, generation_info
            )
            yield chunk

    def _generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[CallbackManagerForLLMRun] = None,
            **kwargs
    ) -> Any:
        """Handle non-streaming calls, extract think content to reasoning_content field."""
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self._process_generations(result.generations, is_async=False)
        return result

    async def _agenerate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs
    ) -> ChatResult:
        """Handle async non-streaming calls, extract think content to reasoning_content field."""
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self._process_generations(result.generations, is_async=True)
        return result

    def _stream(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[CallbackManagerForLLMRun] = None,
            **kwargs
    ) -> Iterator[ChatGenerationChunk]:
        """Process streaming output, modifying chunks to add reasoning_content field."""
        logger.debug("CustomChatOllamaWithReasoning._stream called")
        self._reset_think_state()

        try:
            for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield from self._process_stream_chunk(chunk)
        except Exception as e:
            logger.error(f"Error in CustomChatOllamaWithReasoning stream processing: {e}")
            raise

    async def _astream(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Process async streaming output, modifying chunks to add reasoning_content field."""
        logger.debug("CustomChatOllamaWithReasoning._astream called")
        self._reset_think_state()

        try:
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                for processed_chunk in self._process_stream_chunk(chunk):
                    yield processed_chunk
        except Exception as e:
            logger.error(f"Error in CustomChatOllamaWithReasoning async stream processing: {e}")
            raise

    # Helper methods for better code organization

    def _reset_think_state(self) -> None:
        """Reset think state at the start of processing."""
        self.in_think = False

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

    def _build_additional_kwargs(self, reasoning: bool, content: str) -> dict:
        """Build additional kwargs for chunk."""
        additional_kwargs = {}
        if reasoning and self.in_think and content:
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

    def _process_generations(self, generations: List, is_async: bool = False) -> None:
        """Process generations to extract think content."""
        if not generations:
            return

        async_prefix = "Async " if is_async else ""

        for generation in generations:
            try:
                self._process_generation_message(generation, async_prefix)
                self._process_generation_text(generation, async_prefix)
            except Exception as e:
                logger.error(f"{async_prefix}Error processing generation: {e}")

    def _process_generation_message(self, generation, async_prefix: str) -> None:
        """Process generation message content."""
        if not (hasattr(generation, 'message') and
                hasattr(generation.message, 'content')):
            return

        original_content = generation.message.content
        reasoning_content, cleaned_content = self._extract_think_content(original_content)

        generation.message.content = cleaned_content

        if not hasattr(generation.message, 'additional_kwargs'):
            generation.message.additional_kwargs = {}
        generation.message.additional_kwargs['reasoning_content'] = reasoning_content or None

        logger.debug(
            f"{async_prefix}Original content length: {len(original_content)}, "
            f"reasoning length: {len(reasoning_content)}, "
            f"processed length: {len(cleaned_content)}"
        )

    def _process_generation_text(self, generation, async_prefix: str) -> None:
        """Process generation text content."""
        if not hasattr(generation, 'text'):
            return

        original_text = generation.text
        reasoning_content, cleaned_text = self._extract_think_content(original_text)
        generation.text = cleaned_text

        logger.debug(
            f"{async_prefix}Original text length: {len(original_text)}, "
            f"processed length: {len(cleaned_text)}"
        )

    def _extract_think_content(self, content: str) -> Tuple[str, str]:
        """
        Extract think tag content and return (reasoning_content, cleaned_content).

        Args:
            content: Original content with potential think tags

        Returns:
            Tuple of (reasoning_content, cleaned_content)
        """
        if not content:
            return "", ""

        # Extract content inside think tags
        think_matches = self.THINK_PATTERN.findall(content)
        reasoning_content = '\n'.join(think_matches).strip() if think_matches else ''

        # Remove entire <think>...</think> blocks
        cleaned_content = self.THINK_REMOVAL_PATTERN.sub('', content).strip()

        return reasoning_content, cleaned_content

    def _process_stream_chunk(self, chunk: ChatGenerationChunk) -> Iterator[ChatGenerationChunk]:
        """Process a single stream chunk and yield modified chunks."""
        if not (hasattr(chunk, 'message') and hasattr(chunk.message, 'content')):
            # Add reasoning_content field for chunks without content
            self._ensure_reasoning_content_field(chunk)
            yield chunk
            return

        content = chunk.message.content or ""

        if not content:
            self._ensure_reasoning_content_field(chunk)
            yield chunk
            return

        logger.debug(f"Processing chunk content: '{content}', in_think state: {self.in_think}")

        # Process content with think tags
        modified_chunks = self._process_chunk_with_think_tags(chunk, content)

        # Yield all modified chunks
        yield from modified_chunks

    def _ensure_reasoning_content_field(self, chunk: ChatGenerationChunk) -> None:
        """Ensure chunk has reasoning_content field set to None."""
        if not hasattr(chunk, 'message') or not chunk.message:
            return

        if not hasattr(chunk.message, 'additional_kwargs'):
            chunk.message.additional_kwargs = {}
        chunk.message.additional_kwargs['reasoning_content'] = None

    def _process_chunk_with_think_tags(
            self,
            original_chunk: ChatGenerationChunk,
            content: str
    ) -> List[ChatGenerationChunk]:
        """
        Process chunk containing think tags and return list of modified chunks.

        Args:
            original_chunk: Original chunk from parent stream
            content: Text content of the chunk

        Returns:
            List of modified chunks with proper content/reasoning_content fields
        """
        chunks = []
        current_pos = 0

        while current_pos < len(content):
            if not self.in_think:
                current_pos = self._process_outside_think_tags(
                    chunks, original_chunk, content, current_pos
                )
            else:
                current_pos = self._process_inside_think_tags(
                    chunks, original_chunk, content, current_pos
                )

            if current_pos < 0:  # Break condition
                break

        return chunks

    def _process_outside_think_tags(
            self,
            chunks: List[ChatGenerationChunk],
            original_chunk: ChatGenerationChunk,
            content: str,
            current_pos: int
    ) -> int:
        """Process content when outside think tags."""
        think_start = content.find(self.THINK_START_TAG, current_pos)

        if think_start != -1:
            # Found <think> tag, output content before it
            before_think = content[current_pos:think_start]
            if before_think:
                chunk = self._create_content_chunk(original_chunk, before_think)
                chunks.append(chunk)

            # Enter think state, skip <think> tag and optional newline
            new_pos = think_start + len(self.THINK_START_TAG)
            if new_pos < len(content) and content[new_pos] == '\n':
                new_pos += 1

            self.in_think = True
            return new_pos
        else:
            # No <think> tag found, output remaining content
            remaining = content[current_pos:]
            if remaining:
                chunk = self._create_content_chunk(original_chunk, remaining)
                chunks.append(chunk)
            return -1  # Break condition

    def _process_inside_think_tags(
            self,
            chunks: List[ChatGenerationChunk],
            original_chunk: ChatGenerationChunk,
            content: str,
            current_pos: int
    ) -> int:
        """Process content when inside think tags."""
        think_end = content.find(self.THINK_END_TAG, current_pos)

        if think_end != -1:
            # Found </think> tag, output reasoning content
            reasoning = content[current_pos:think_end]
            if reasoning:
                chunk = self._create_reasoning_chunk(original_chunk, reasoning)
                chunks.append(chunk)

            # Exit think state, skip </think> tag and optional newline
            new_pos = think_end + len(self.THINK_END_TAG)
            if new_pos < len(content) and content[new_pos] == '\n':
                new_pos += 1

            self.in_think = False
            return new_pos
        else:
            # No </think> tag found, output remaining reasoning content
            remaining_reasoning = content[current_pos:]
            if remaining_reasoning:
                chunk = self._create_reasoning_chunk(original_chunk, remaining_reasoning)
                chunks.append(chunk)
            return -1  # Break condition

    def _create_content_chunk(
            self,
            original_chunk: ChatGenerationChunk,
            content: str
    ) -> ChatGenerationChunk:
        """Create a chunk for regular content."""
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content=content,
                additional_kwargs={'reasoning_content': None}
            ),
            generation_info=original_chunk.generation_info
        )

    def _create_reasoning_chunk(
            self,
            original_chunk: ChatGenerationChunk,
            reasoning_content: str
    ) -> ChatGenerationChunk:
        """Create a chunk for reasoning content."""
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                additional_kwargs={'reasoning_content': reasoning_content}
            ),
            generation_info=original_chunk.generation_info
        )

    # Deprecated method kept for backward compatibility
    def _remove_think_tags(self, content: str) -> str:
        """Remove think tags, keeping only content outside tags. (Deprecated)"""
        logger.warning("_remove_think_tags is deprecated, use _extract_think_content instead")
        _, cleaned_content = self._extract_think_content(content)
        return cleaned_content
