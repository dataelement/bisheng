from typing import Optional, Any

from langchain_core.language_models import LanguageModelInput
from langchain_openai import ChatOpenAI


class ChatOpenAICompatible(ChatOpenAI):
    """
    A ChatOpenAI subclass that ensures compatibility with older parameter names.
    use max_tokens instead of max_completion_tokens.
    """

    def _get_request_payload(
            self,
            input_: LanguageModelInput,
            *,
            stop: Optional[list[str]] = None,
            **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # max_tokens was deprecated in favor of max_completion_tokens
        # in September 2024 release
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload.pop("max_completion_tokens")
        return payload
