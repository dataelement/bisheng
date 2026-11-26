from __future__ import annotations

import asyncio
import json
from time import monotonic
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatResult
from pydantic import Field

from .chat_openai_compatible import ChatOpenAICompatible

_WEB_SEARCH_TOOL = {
    "type": "builtin_function",
    "function": {"name": "$web_search"},
}


class ChatMoonshot(ChatOpenAICompatible):
    """Moonshot (Kimi, OpenAI-compatible) chat model.

    Moonshot exposes web search via the builtin ``$web_search`` function: the
    model emits a ``$web_search`` tool call which the client must echo back so
    the model can continue. When ``enable_web_search`` is set, this class
    advertises the tool and runs that tool-call feedback loop internally — logic
    that previously lived in ``BishengLLM.moonshot_generate``.

    The loop relies on non-streaming inner calls, so the provider's params
    handler forces ``streaming=False``.
    """

    enable_web_search: bool = Field(default=False)
    max_tool_rounds: int = Field(default=8, ge=1, le=32)
    tool_loop_timeout: float = Field(default=60, gt=0, le=300)

    @staticmethod
    def _needs_continuation(result: ChatResult) -> bool:
        if not result.generations:
            raise RuntimeError("Moonshot returned no generations")
        generation = result.generations[0]
        reason = (generation.generation_info or {}).get("finish_reason")
        if reason in {"stop", "length", "content_filter"}:
            return False
        if reason != "tool_calls" or not generation.message.tool_calls:
            raise RuntimeError("Moonshot returned a non-progressing or unknown finish state")
        return True

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if self.enable_web_search:
            tools = payload.get("tools") or []
            if not any(tool.get("type") == "builtin_function" for tool in tools):
                tools.append(dict(_WEB_SEARCH_TOOL))
            payload["tools"] = tools
        return payload

    @staticmethod
    def _feed_web_search_results(
        messages: list[BaseMessage],
        result: ChatResult,
    ) -> bool:
        """Append the assistant message + tool results for any ``$web_search``
        call so the next round can continue. Returns False once a non-web-search
        tool call is hit (mirrors the original break semantics)."""
        result_message = result.generations[0].message
        for tool_call in result_message.tool_calls:
            if tool_call["name"] == "$web_search":
                messages.append(result_message)
                messages.append(
                    ToolMessage(
                        tool_call_id=tool_call["id"],
                        name=tool_call["name"],
                        content=json.dumps(tool_call["args"], ensure_ascii=False),
                    )
                )
            else:
                return False
        return True

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.enable_web_search:
            return super()._generate(messages, stop, run_manager, **kwargs)
        messages = list(messages)
        deadline = monotonic() + self.tool_loop_timeout
        for _ in range(self.max_tool_rounds):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Moonshot continuation deadline exceeded")
            # Also cap SDK retries: they must not multiply the local call budget.
            root_client = self.root_client.with_options(timeout=remaining, max_retries=0)
            client = self.model_copy(update={"client": root_client.chat.completions, "root_client": root_client})
            result = super(ChatMoonshot, client)._generate(messages, stop, run_manager, **kwargs)
            if monotonic() >= deadline:
                raise TimeoutError("Moonshot continuation deadline exceeded")
            if not self._needs_continuation(result):
                return result
            if not self._feed_web_search_results(messages, result):
                return result  # External tool calls remain the caller's responsibility.
        raise RuntimeError("Moonshot continuation exceeded max_tool_rounds")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.enable_web_search:
            return await super()._agenerate(messages, stop, run_manager, **kwargs)
        messages = list(messages)
        deadline = monotonic() + self.tool_loop_timeout
        async with asyncio.timeout(self.tool_loop_timeout):
            for _ in range(self.max_tool_rounds):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Moonshot continuation deadline exceeded")
                root_client = self.root_async_client.with_options(timeout=remaining, max_retries=0)
                client = self.model_copy(
                    update={"async_client": root_client.chat.completions, "root_async_client": root_client}
                )
                result = await super(ChatMoonshot, client)._agenerate(messages, stop, run_manager, **kwargs)
                if monotonic() >= deadline:
                    raise TimeoutError("Moonshot continuation deadline exceeded")
                if not self._needs_continuation(result):
                    return result
                if not self._feed_web_search_results(messages, result):
                    return result
        raise RuntimeError("Moonshot continuation exceeded max_tool_rounds")
