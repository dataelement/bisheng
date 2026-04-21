from __future__ import annotations

from typing import Any, Optional

import openai
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


def _get_reasoning_content(message: dict[str, Any]) -> Optional[str]:
    if (reasoning_content := message.get("reasoning_content")) is not None:
        return reasoning_content
    if (reasoning := message.get("reasoning")) is not None:
        return reasoning
    return None


class ChatOpenAIReasoning(ChatOpenAI):
    """ChatOpenAI with reasoning extraction support."""

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
        if (choices := chunk.get("choices")) and generation_chunk:
            top = choices[0]
            if isinstance(generation_chunk.message, AIMessageChunk):
                if (
                    reasoning_content := top.get("delta", {}).get("reasoning_content")
                ) is not None:
                    generation_chunk.message.additional_kwargs["reasoning_content"] = (
                        reasoning_content
                    )
                elif (reasoning := top.get("delta", {}).get("reasoning")) is not None:
                    generation_chunk.message.additional_kwargs["reasoning_content"] = (
                        reasoning
                    )

        return generation_chunk

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: Optional[dict] = None,
    ) -> ChatResult:
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()

        for generation, choice in zip(chat_result.generations, response_dict.get("choices", [])):
            if not isinstance(generation.message, AIMessage):
                continue
            reasoning_content = _get_reasoning_content(choice.get("message", {}))
            if reasoning_content is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning_content

        return chat_result
