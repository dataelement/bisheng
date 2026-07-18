from __future__ import annotations

import json
from typing import Any, Optional

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

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: Optional[list[str]] = None,
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
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.enable_web_search:
            return super()._generate(messages, stop, run_manager, **kwargs)
        messages = list(messages)
        result = None
        finish_reason = None
        while finish_reason is None or finish_reason == "tool_calls":
            result = super()._generate(messages, stop, run_manager, **kwargs)
            finish_reason = result.generations[0].generation_info.get("finish_reason")
            if not self._feed_web_search_results(messages, result):
                break
        return result

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.enable_web_search:
            return await super()._agenerate(messages, stop, run_manager, **kwargs)
        messages = list(messages)
        result = None
        finish_reason = None
        while finish_reason is None or finish_reason == "tool_calls":
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)
            finish_reason = result.generations[0].generation_info.get("finish_reason")
            if not self._feed_web_search_results(messages, result):
                break
        return result
