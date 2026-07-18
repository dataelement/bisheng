from __future__ import annotations

from typing import Any

import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


def _get_reasoning_content(message: dict[str, Any]) -> str | None:
    if (reasoning_content := message.get("reasoning_content")) is not None:
        return reasoning_content
    if (reasoning := message.get("reasoning")) is not None:
        return reasoning
    return None


def _convert_standard_image_block(content_part: Any) -> Any:
    if not isinstance(content_part, dict) or content_part.get("type") != "image":
        return content_part

    source_type = content_part.get("source_type")
    mime_type = content_part.get("mime_type") or "image/jpeg"
    data = content_part.get("data")
    url = content_part.get("url")

    source = content_part.get("source")
    if isinstance(source, dict):
        source_type = source_type or source.get("type")
        mime_type = source.get("media_type") or source.get("mime_type") or mime_type
        data = data or source.get("data")
        url = url or source.get("url")

    if source_type == "base64" and data:
        image_url = {"url": f"data:{mime_type};base64,{data}"}
    elif source_type == "url" and url:
        image_url = {"url": url}
    else:
        return content_part

    if detail := content_part.get("detail"):
        image_url["detail"] = detail

    return {"type": "image_url", "image_url": image_url}


def _normalize_openai_image_content(payload: dict[str, Any]) -> None:
    for message in payload.get("messages", []):
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        message["content"] = [_convert_standard_image_block(part) for part in message["content"]]


class ChatOpenAIReasoning(ChatOpenAI):
    """ChatOpenAI with reasoning extraction support."""

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        _normalize_openai_image_content(payload)
        return payload

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
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
        generation_info: dict | None = None,
    ) -> ChatResult:
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()

        for generation, choice in zip(chat_result.generations, response_dict.get("choices", []), strict=False):
            if not isinstance(generation.message, AIMessage):
                continue
            reasoning_content = _get_reasoning_content(choice.get("message", {}))
            if reasoning_content is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning_content

        return chat_result
