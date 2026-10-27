from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_deepseek import ChatDeepSeek

from .reasoning_passback import attach_reasoning


class CustomChatDeepSeek(ChatDeepSeek):
    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # With tools the official API requires the key on every assistant message.
        return attach_reasoning(payload, self._convert_input(input_).to_messages(), missing="")
