from typing import Optional, Any

from langchain_core.language_models import LanguageModelInput

from .chat_openai_compatible import ChatOpenAICompatible


class ChatVoiceEngine(ChatOpenAICompatible):
    """
    VoiceEngine requires assistant history messages to contain `status`
    when web_search tool is enabled.
    """

    @staticmethod
    def _has_web_search_tool(payload: dict, kwargs: dict[str, Any]) -> bool:
        tools = kwargs.get("tools", payload.get("tools", []))
        if not isinstance(tools, list):
            return False

        for tool in tools:
            if isinstance(tool, dict) and tool.get("type") == "web_search":
                return True
        return False

    def _get_request_payload(
            self,
            input_: LanguageModelInput,
            *,
            stop: Optional[list[str]] = None,
            **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        if not self._has_web_search_tool(payload, kwargs):
            return payload

        for payload_msg in payload.get("messages", []) or payload.get("input", []):
            if payload_msg.get("role") == "assistant" and "status" not in payload_msg:
                payload_msg["status"] = "completed"

        return payload
