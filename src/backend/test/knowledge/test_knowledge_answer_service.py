"""Fail-closed, stateless orchestration with phase cancellation boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from bisheng.common.errcode.knowledge import (
    KnowledgeAnswerModelError,
    KnowledgeAnswerRetrievalError,
    KnowledgeAnswerTimeoutError,
    KnowledgeTypeNotSupportedError,
)
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerReq
from bisheng.knowledge.domain.services import knowledge_space_answer_service as module


def test_failure_logs_keep_stack_locations_without_secrets_or_locals():
    messages = []
    sink = module.logger.add(lambda message: messages.append(str(message)), format="{message}", level="ERROR")
    try:
        try:
            raise RuntimeError("api_key=private-diagnostic-secret")
        except RuntimeError as cause:
            error = KnowledgeAnswerModelError()
            error.__cause__ = cause
            module._log_failure(error, phase="generation", code=10964)
        output = "".join(messages)
        assert "error_code=10964" in output
        assert "test_failure_logs_keep_stack_locations" in output
        assert "private-diagnostic-secret" not in output
        assert "api_key=" not in output
    finally:
        module.logger.remove(sink)


@pytest.fixture()
def setup_service():
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=SimpleNamespace(type=module.KnowledgeTypeEnum.SPACE.value))
    )
    retrieval = SimpleNamespace(_require_space_view_permission=AsyncMock(), aretrieve_chunks=AsyncMock(return_value=[]))
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="answer")))
    model = SimpleNamespace(prepare=AsyncMock(return_value=llm))
    service = module.KnowledgeSpaceAnswerService(
        login_user=SimpleNamespace(user_id=7),
        knowledge_repository=repository,
        retrieval_service=retrieval,
        model_service=model,
    )
    return service, repository, retrieval, model, llm


def req(**changes):
    return KnowledgeAnswerReq(query="question", knowledge_base_ids=[2, 1, 2], model_id=3, **changes)


def result(space=1):
    return [
        (
            space,
            Document(page_content="evidence", metadata={"document_id": 11, "chunk_index": 0, "document_name": "file"}),
        )
    ]


async def test_all_permissions_checked_before_model_or_recall(setup_service):
    service, repository, retrieval, model, llm = setup_service
    calls = []

    async def permission(space):
        calls.append(space)
        model.prepare.assert_not_awaited()
        retrieval.aretrieve_chunks.assert_not_awaited()
        if space == 2:
            raise HTTPException(403, "denied")

    retrieval._require_space_view_permission.side_effect = permission
    with pytest.raises(HTTPException) as caught:
        await service.answer(req())
    assert caught.value.status_code == 403
    assert calls == [1, 2]
    assert repository.find_by_id.await_count == 2
    model.prepare.assert_not_awaited()
    llm.ainvoke.assert_not_awaited()


async def test_wrong_resource_type_prevents_model_and_recall(setup_service):
    service, repository, retrieval, model, _ = setup_service
    repository.find_by_id.return_value.type = -1
    with pytest.raises(KnowledgeTypeNotSupportedError):
        await service.answer(req())
    retrieval.aretrieve_chunks.assert_not_awaited()
    model.prepare.assert_not_awaited()


async def test_empty_recall_validates_model_but_does_not_generate(setup_service):
    service, _, retrieval, model, llm = setup_service
    response = await service.answer(req())
    assert response.model_dump() == {"answer": "未找到相关内容", "has_context": False, "model_id": 3, "references": []}
    model.prepare.assert_awaited_once_with(model_id=3, user_id=7)
    llm.ainvoke.assert_not_awaited()
    assert [call.kwargs["knowledge_base_ids"] for call in retrieval.aretrieve_chunks.await_args_list] == [[1], [2]]


async def test_success_reuses_single_space_recall_and_independent_messages(setup_service):
    service, _, retrieval, _, llm = setup_service
    retrieval.aretrieve_chunks.side_effect = [result(), []]
    response = await service.answer(
        req(filters={"knowledge_base_filters": [{"knowledge_base_id": 2, "tags": ["tag"]}]})
    )
    assert response.answer == "answer" and response.has_context
    assert response.references[0].document_id == 11
    assert retrieval.aretrieve_chunks.await_args_list[0].kwargs["kb_filters"] is None
    assert retrieval.aretrieve_chunks.await_args_list[1].kwargs["kb_filters"] == {
        2: {"knowledge_base_id": 2, "tags": ["tag"], "tag_match_mode": "ANY"}
    }
    messages = llm.ainvoke.await_args.args[0]
    assert len(messages) == 2
    assert messages[0].type == "system" and messages[1].type == "human"
    assert "evidence" in messages[1].content and "question" in messages[1].content
    retrieval.aretrieve_chunks.side_effect = [[], []]
    await service.answer(req())
    assert llm.ainvoke.await_count == 1


async def test_out_of_scope_result_is_error_not_context(setup_service):
    service, _, retrieval, _, llm = setup_service
    retrieval.aretrieve_chunks.return_value = result(999)
    with pytest.raises(KnowledgeAnswerRetrievalError):
        await service.answer(req())
    llm.ainvoke.assert_not_awaited()


@pytest.mark.parametrize(
    "phase,expected", [("retrieval", KnowledgeAnswerRetrievalError), ("generation", KnowledgeAnswerModelError)]
)
async def test_dependency_failures_keep_cause_and_never_return_partial(setup_service, phase, expected):
    service, _, retrieval, _, llm = setup_service
    secret = RuntimeError("provider secret must stay internal")
    retrieval.aretrieve_chunks.side_effect = [result(), []]
    target = retrieval.aretrieve_chunks if phase == "retrieval" else llm.ainvoke
    target.side_effect = secret
    with pytest.raises(expected) as caught:
        await service.answer(req())
    assert caught.value.__cause__ is secret
    assert "secret" not in caught.value.message


async def test_permission_outage_propagates_without_generation(setup_service):
    service, _, retrieval, _, llm = setup_service
    error = PermissionServiceUnavailableError()
    retrieval.aretrieve_chunks.side_effect = error
    with pytest.raises(PermissionServiceUnavailableError) as caught:
        await service.answer(req())
    assert caught.value is error
    llm.ainvoke.assert_not_awaited()


@pytest.mark.parametrize("phase", ["admission", "retrieval", "generation"])
async def test_timeout_cancels_local_pending_phase(setup_service, monkeypatch, phase):
    service, _, retrieval, model, llm = setup_service
    retrieval.aretrieve_chunks.side_effect = [result(), []]
    cancelled = asyncio.Event()

    async def pending(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    target = {"admission": model.prepare, "retrieval": retrieval.aretrieve_chunks, "generation": llm.ainvoke}[phase]
    target.side_effect = pending
    original_timeout = asyncio.timeout
    phase_seconds = {"admission": 120, "retrieval": 30, "generation": 90}[phase]
    monkeypatch.setattr(
        module.asyncio, "timeout", lambda seconds: original_timeout(0.02 if seconds == phase_seconds else seconds)
    )
    with pytest.raises(KnowledgeAnswerTimeoutError):
        await service.answer(req())
    assert cancelled.is_set()


@pytest.mark.parametrize("phase", ["admission", "retrieval", "generation"])
async def test_caller_cancellation_is_never_laundered(setup_service, phase):
    service, _, retrieval, model, llm = setup_service
    retrieval.aretrieve_chunks.side_effect = [result(), []]
    target = {"admission": model.prepare, "retrieval": retrieval.aretrieve_chunks, "generation": llm.ainvoke}[phase]
    target.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.answer(req())


@pytest.mark.parametrize(
    "error", [HTTPException(401, "private-secret"), KnowledgeTypeNotSupportedError(msg="private-secret")]
)
async def test_provider_business_and_http_errors_are_sanitized(setup_service, error):
    service, _, retrieval, _, llm = setup_service
    retrieval.aretrieve_chunks.side_effect = [result(), []]
    llm.ainvoke.side_effect = error
    with pytest.raises(KnowledgeAnswerModelError) as caught:
        await service.answer(req())
    assert caught.value.__cause__ is error
    assert "private-secret" not in caught.value.message


async def test_unknown_admission_failure_is_retrieval_error(setup_service):
    service, repository, retrieval, model, _ = setup_service
    repository.find_by_id.side_effect = RuntimeError("database unavailable")
    with pytest.raises(KnowledgeAnswerRetrievalError):
        await service.answer(req())
    retrieval.aretrieve_chunks.assert_not_awaited()
    model.prepare.assert_not_awaited()
