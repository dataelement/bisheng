from __future__ import annotations

from typing import Any, Optional

from langchain_core.language_models import LanguageModelInput
from pydantic import Field

from .chat_openai_compatible import ChatOpenAICompatible


class ChatMinimax(ChatOpenAICompatible):
    """MiniMax (OpenAI-compatible) chat model with optional built-in web search.

    When ``enable_web_search`` is set the MiniMax ``web_search`` tool is appended
    to every request (unless the caller already supplied it). This previously
    lived in ``BishengLLM.parse_kwargs``; encapsulating it here also makes web
    search work on the streaming path, which the old generate-only branch missed.
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
            if not any(tool.get("type") == "web_search" for tool in tools):
                tools.append({"type": "web_search"})
            payload["tools"] = tools
        return payload
