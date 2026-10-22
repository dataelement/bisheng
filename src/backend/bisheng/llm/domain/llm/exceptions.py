"""Exceptions raised by ``BishengLLM`` on top of the provider SDK errors."""

from typing import Any

from langchain_core.exceptions import ContextOverflowError


class LLMContextOverflowError(ContextOverflowError):
    """The provider rejected a request because it exceeds the model's context window.

    Used for provider SDKs that langchain has no context-overflow subclass for.
    OpenAI and Anthropic SDK errors are re-raised as langchain's own
    ``OpenAIContextOverflowError`` / ``AnthropicContextOverflowError`` instead, so
    they stay instances of the original SDK error type. ``body`` and
    ``status_code`` are copied from the original error so code that reads the
    provider's message from them keeps working.
    """

    def __init__(
        self,
        message: str,
        *,
        body: Any = None,
        status_code: int | None = None,
        reported_input_tokens: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.body = body
        self.status_code = status_code
        self.reported_input_tokens = reported_input_tokens
