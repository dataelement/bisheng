from __future__ import annotations

from typing import Optional

import openai
from langchain_core.messages import BaseMessage, BaseMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from .chat_openai_compatible import ChatOpenAICompatible


def _flatten_qwen_content(
    message: BaseMessage | BaseMessageChunk,
) -> BaseMessage | BaseMessageChunk:
    """Qwen VL models return ``content`` as a list of content parts; downstream
    BiSheng code expects a plain string, so concatenate the text parts."""
    if isinstance(message.content, list):
        message.content = "".join(one.get("text", "") for one in message.content)
    return message


class ChatQwen(ChatOpenAICompatible):
    """Qwen (DashScope OpenAI-compatible) chat model.

    Encapsulates the VL list-content flattening that previously lived in
    ``BishengLLM`` as per-call ``convert_qwen_result`` branches, so the wrapper
    stays provider-agnostic.
    """

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: Optional[dict] = None,
    ) -> ChatResult:
        chat_result = super()._create_chat_result(response, generation_info)
        for generation in chat_result.generations:
            _flatten_qwen_content(generation.message)
        return chat_result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: Optional[dict],
    ) -> Optional[ChatGenerationChunk]:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk:
            _flatten_qwen_content(generation_chunk.message)
        return generation_chunk
