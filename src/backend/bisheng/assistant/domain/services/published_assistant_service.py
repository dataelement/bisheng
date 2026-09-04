"""Shared assistant behavior for the v2 key and v3 publication adapters."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from loguru import logger

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.llm.domain.utils import extract_reasoning_content
from bisheng.utils import generate_uuid


@dataclass(frozen=True, slots=True)
class AssistantCompletion:
    payload: dict | None
    stream: AsyncIterator[str] | None


class PublishedAssistantService:
    @staticmethod
    async def get_info(assistant_id: str, operator: UserPayload):
        return await AssistantService.get_assistant_info(assistant_id, operator)

    @staticmethod
    async def validate_websocket_session(
        *,
        assistant_id: str,
        chat_id: str | None,
        session_subject: SessionSubject,
    ) -> None:
        if not chat_id:
            return
        session = await ChatSessionService.get_subject_session_if_exists(chat_id, session_subject)
        if session is not None and session.flow_id != assistant_id:
            raise NotFoundError.http_exception()

    @staticmethod
    def _supports_streaming(agent: AssistantAgent) -> bool:
        try:
            if getattr(agent, "llm", None):
                if hasattr(agent.llm, "streaming"):
                    return bool(agent.llm.streaming)
                if getattr(agent.llm, "llm", None) is not None and hasattr(agent.llm.llm, "streaming"):
                    return bool(agent.llm.llm.streaming)
            return True
        except Exception:
            logger.opt(exception=True).warning("failed to inspect assistant streaming support")
            return True

    @classmethod
    async def complete(
        cls,
        *,
        assistant_id: str,
        model: str,
        messages: list[dict],
        stream: bool,
        temperature: float,
        operator: UserPayload,
    ) -> tuple[AssistantCompletion, object]:
        assistant_info = await cls.get_info(assistant_id, operator)
        if temperature != 0:
            assistant_info.temperature = temperature

        history = []
        question = ""
        for item in messages:
            if item.get("role") == "user":
                history.append(HumanMessage(content=item.get("content", "")))
                question = item.get("content", "")
            elif item.get("role") == "assistant":
                history.append(AIMessage(content=item.get("content", "")))
        if history and history[-1].content == question:
            history = history[:-1]

        agent = AssistantAgent(assistant_info, "", invoke_user_id=operator.user_id)
        await agent.init_assistant()
        supports_streaming = cls._supports_streaming(agent)
        response_id = generate_uuid()

        if not stream or not supports_streaming:
            answer_messages = await agent.run(question, history)
            answer = answer_messages[-1].content
            if not stream:
                return (
                    AssistantCompletion(
                        payload={
                            "id": response_id,
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": answer},
                                    "finish_reason": "stop",
                                    "delta": None,
                                }
                            ],
                            "usage": None,
                            "system_fingerprint": None,
                        },
                        stream=None,
                    ),
                    assistant_info,
                )

            async def pseudo_stream() -> AsyncIterator[str]:
                chunk = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": None,
                            "finish_reason": "stop",
                            "delta": {"content": answer},
                        }
                    ],
                    "usage": None,
                    "system_fingerprint": None,
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return AssistantCompletion(payload=None, stream=pseudo_stream()), assistant_info

        async def streaming_events() -> AsyncIterator[str]:
            try:
                async for message_chunk in agent.astream(question, history):
                    if not message_chunk:
                        continue
                    latest = message_chunk[-1] if isinstance(message_chunk, list) else message_chunk
                    if not isinstance(latest, AIMessageChunk):
                        continue
                    chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content": latest.content,
                                    "reasoning_content": extract_reasoning_content(latest),
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
                end_chunk = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(end_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                logger.opt(exception=True).error("assistant streaming failed")
                error_chunk = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"Error-free: {exc!s}"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return AssistantCompletion(payload=None, stream=streaming_events()), assistant_info


__all__ = ["AssistantCompletion", "PublishedAssistantService"]
