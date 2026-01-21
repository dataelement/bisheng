from typing import Optional, Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek


class CustomChatDeepSeek(ChatDeepSeek):

    def _get_request_payload(
            self,
            input_: LanguageModelInput,
            *,
            stop: Optional[list[str]] = None,
            **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()

        for payload_msg, msg in zip(payload['messages'], messages):
            if isinstance(msg, AIMessage):
                payload_msg['reasoning_content'] = msg.additional_kwargs.get('reasoning_content', '')

        return payload
