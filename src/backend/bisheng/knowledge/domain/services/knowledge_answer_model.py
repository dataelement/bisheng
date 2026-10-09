"""Use tenant-selected BiSheng models without tools or built-in web search."""

import json

from fastapi import HTTPException
from langchain_core.messages import AIMessage

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.knowledge import KnowledgeAnswerFormatError, KnowledgeAnswerModelError
from bisheng.common.errcode.server import (
    LlmModelConfigDeletedError,
    LlmModelOfflineError,
    LlmModelTypeError,
    LlmProviderDeletedError,
)
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.llm.base import BishengBase

_TOOL_OPTIONS = frozenset(
    {
        "tools",
        "functions",
        "tool_choice",
        "function_call",
        "builtin_tools",
        "enable_search",
        "enable_web_search",
        "web_search",
        "web_search_options",
    }
)


def _assert_no_tools(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _TOOL_OPTIONS and item not in (None, False, "none", [], {}):
                raise HTTPException(400, "select a model without built-in search or tools")
            if key in {"user_kwargs", "model_kwargs", "extra_body"} and isinstance(item, str):
                try:
                    item = json.loads(item)
                except ValueError as exc:
                    raise KnowledgeAnswerModelError() from exc
                if not isinstance(item, dict):
                    raise KnowledgeAnswerModelError()
            _assert_no_tools(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_tools(item)


class KnowledgeAnswerModel:
    async def prepare(self, *, model_id: int, user_id: int):
        config = await LLMService.get_workbench_llm()
        if str(model_id) not in {str(item.id) for item in config.models or []}:
            raise HTTPException(400, "model is not available in the current tenant workbench")
        model, server = await BishengBase.get_model_server_info(model_id)
        if model is None:
            raise LlmModelConfigDeletedError()
        if server is None:
            raise LlmProviderDeletedError()
        if model.model_type != LLMModelType.LLM.value:
            raise LlmModelTypeError(model_type=model.model_type)
        if not model.online:
            raise LlmModelOfflineError(server_name=server.name, model_name=model.model_name)
        _assert_no_tools(model.config or {})
        _assert_no_tools(server.config or {})
        try:
            return await LLMService.get_bisheng_llm(
                model_id=model_id,
                user_id=user_id,
                app_id="knowledge_answer",
                app_name="knowledge_answer",
                app_type=ApplicationTypeEnum.KNOWLEDGE_SPACE,
            )
        except Exception as exc:
            # Provider initialization errors can contain credentials or URLs.
            raise KnowledgeAnswerModelError() from exc


def extract_answer_text(message: AIMessage) -> str:
    if (
        message.tool_calls
        or message.invalid_tool_calls
        or message.additional_kwargs.get("tool_calls")
        or message.additional_kwargs.get("function_call")
    ):
        raise KnowledgeAnswerFormatError()
    content = message.content
    if isinstance(content, list):
        if any(
            not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str)
            for item in content
        ):
            raise KnowledgeAnswerFormatError()
        content = "".join(item["text"] for item in content)
    if not isinstance(content, str) or not content.strip():
        raise KnowledgeAnswerFormatError()
    return content.strip()
