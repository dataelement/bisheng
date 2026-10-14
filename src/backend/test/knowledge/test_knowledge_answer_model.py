"""Model admission and complete text-only output boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from bisheng.common.errcode.knowledge import KnowledgeAnswerFormatError, KnowledgeAnswerModelError
from bisheng.common.errcode.server import (
    LlmModelConfigDeletedError,
    LlmModelOfflineError,
    LlmModelTypeError,
    LlmProviderDeletedError,
)
from bisheng.knowledge.domain.services import knowledge_answer_model as module


@pytest.fixture()
def configured(monkeypatch):
    model = SimpleNamespace(model_type=module.LLMModelType.LLM.value, online=True, config={}, model_name="test")
    server = SimpleNamespace(name="provider", config={})
    monkeypatch.setattr(
        module.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(models=[SimpleNamespace(id="3")])),
    )
    info = AsyncMock(return_value=(model, server))
    factory = AsyncMock(return_value=object())
    monkeypatch.setattr(module.BishengBase, "get_model_server_info", info)
    monkeypatch.setattr(module.LLMService, "get_bisheng_llm", factory)
    return model, server, info, factory


async def test_only_selected_model_uses_existing_factory(configured):
    _, _, _, factory = configured
    result = await module.KnowledgeAnswerModel().prepare(model_id=3, user_id=7)
    assert result is factory.return_value
    assert factory.await_args.kwargs["model_id"] == 3
    assert factory.await_args.kwargs["user_id"] == 7
    assert factory.await_args.kwargs["app_id"] == "knowledge_answer"


async def test_workbench_unlisted_model_rejected_before_lookup(configured):
    _, _, info, factory = configured
    with pytest.raises(HTTPException) as caught:
        await module.KnowledgeAnswerModel().prepare(model_id=999, user_id=7)
    assert caught.value.status_code == 400
    info.assert_not_awaited()
    factory.assert_not_awaited()


@pytest.mark.parametrize(
    "state,error",
    [
        ("missing_model", LlmModelConfigDeletedError),
        ("missing_provider", LlmProviderDeletedError),
        ("wrong_type", LlmModelTypeError),
        ("offline", LlmModelOfflineError),
    ],
)
async def test_configuration_failures_do_not_fallback(configured, state, error):
    model, server, info, factory = configured
    if state == "missing_model":
        info.return_value = (None, server)
    elif state == "missing_provider":
        info.return_value = (model, None)
    elif state == "wrong_type":
        model.model_type = "embedding"
    else:
        model.online = False
    with pytest.raises(error):
        await module.KnowledgeAnswerModel().prepare(model_id=3, user_id=7)
    factory.assert_not_awaited()


@pytest.mark.parametrize(
    "options",
    [
        {"enable_web_search": True},
        {"tools": [{"type": "web_search"}]},
        {"advanced": {"functions": ["tool"]}},
        {"user_kwargs": '{"extra_body":{"enable_search":true}}'},
        {"model_kwargs": '{"tool_choice":"auto"}'},
    ],
)
@pytest.mark.parametrize("target", ["model", "provider"])
async def test_model_and_provider_tool_options_rejected(configured, options, target):
    model, server, _, factory = configured
    (model if target == "model" else server).config = options
    with pytest.raises(HTTPException):
        await module.KnowledgeAnswerModel().prepare(model_id=3, user_id=7)
    factory.assert_not_awaited()


@pytest.mark.parametrize("options", [{"user_kwargs": "not-json"}, {"model_kwargs": "[]"}])
async def test_invalid_provider_options_fail_closed(configured, options):
    configured[1].config = options
    with pytest.raises(KnowledgeAnswerModelError):
        await module.KnowledgeAnswerModel().prepare(model_id=3, user_id=7)
    configured[3].assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("api_key=private-secret"),
        HTTPException(401, "private-secret"),
        LlmModelConfigDeletedError(msg="private-secret"),
    ],
)
async def test_factory_failure_is_sanitized(configured, error):
    configured[3].side_effect = error
    with pytest.raises(KnowledgeAnswerModelError) as caught:
        await module.KnowledgeAnswerModel().prepare(model_id=3, user_id=7)
    assert caught.value.__cause__ is error
    assert "private-secret" not in caught.value.message


@pytest.mark.parametrize(
    "content,expected",
    [(" answer ", "answer"), ([{"type": "text", "text": "one"}, {"type": "text", "text": "two"}], "onetwo")],
)
def test_extract_complete_text(content, expected):
    assert module.extract_answer_text(AIMessage(content=content)) == expected


@pytest.mark.parametrize(
    "message",
    [
        AIMessage(content=""),
        AIMessage(content=" \n"),
        AIMessage(content=[]),
        AIMessage(content=[{"type": "reasoning", "text": "secret"}]),
        AIMessage(content=["text"]),
        AIMessage(content="answer", additional_kwargs={"function_call": {"name": "tool"}}),
        AIMessage(content="answer", tool_calls=[{"name": "tool", "args": {}, "id": "1"}]),
        AIMessage(content="answer", invalid_tool_calls=[{"name": "tool", "args": "bad", "id": "1", "error": "bad"}]),
    ],
)
def test_output_without_complete_text_or_with_tools_rejected(message):
    with pytest.raises(KnowledgeAnswerFormatError):
        module.extract_answer_text(message)
