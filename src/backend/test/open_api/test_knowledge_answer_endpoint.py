"""New endpoint response adapter, strict validation and sanitized errors."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.errcode.knowledge import (
    KnowledgeAnswerFormatError,
    KnowledgeAnswerModelError,
    KnowledgeAnswerRetrievalError,
    KnowledgeAnswerTimeoutError,
)
from bisheng.common.errcode.open_api import OpenApiAuthDependencyUnavailableError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerResp
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_endpoints.api.endpoints.knowledge_answer import answer_knowledge, router
from bisheng.open_endpoints.api.knowledge_answer_dependencies import get_knowledge_answer_service


@pytest.fixture()
def endpoint():
    app = FastAPI()
    register_open_api_exception_handlers(app)

    @app.middleware("http")
    async def mark_adapter_request_authenticated(request, call_next):
        # This fixture isolates the response adapter; full admission has separate tests.
        request.scope["open_api_principal"] = object()
        return await call_next(request)

    app.include_router(router, prefix="/api/v2")
    service = AsyncMock()
    app.dependency_overrides[get_knowledge_answer_service] = lambda: service
    with TestClient(app) as client:
        yield client, service


BODY = {"query": "question", "knowledge_base_ids": [1], "model_id": 3}


def test_success_uses_unified_contract(endpoint):
    client, service = endpoint
    service.answer.return_value = KnowledgeAnswerResp(answer="answer", has_context=True, model_id=3, references=[])
    response = client.post("/api/v2/filelib/answer", json=BODY)
    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert response.json()["data"] == {"answer": "answer", "has_context": True, "model_id": 3, "references": []}
    service.answer.assert_awaited_once()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (KnowledgeAnswerRetrievalError(), 502, 10963),
        (KnowledgeAnswerModelError(), 502, 10964),
        (KnowledgeAnswerTimeoutError(), 504, 10965),
        (KnowledgeAnswerFormatError(), 502, 10966),
    ],
)
def test_errors_are_sanitized_and_audited(endpoint, error, status, code):
    client, service = endpoint
    error.__cause__ = RuntimeError("api_key=private-secret provider 401 raw")
    service.answer.side_effect = error
    response = client.post("/api/v2/filelib/answer", json=BODY)
    assert response.status_code == status
    assert response.json() == {"status_code": code, "status_message": error.message, "data": None}
    assert "private-secret" not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": 7},
        {"model_id": True},
        {"query": " "},
        {"knowledge_base_ids": []},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 2}]}},
    ],
)
def test_validation_rejects_before_service(endpoint, changes):
    client, service = endpoint
    response = client.post("/api/v2/filelib/answer", json={**BODY, **changes})
    assert response.status_code == 400
    assert response.json()["status_code"] == 400
    service.answer.assert_not_awaited()


async def test_permission_outage_uses_existing_open_api_error():
    from starlette.requests import Request

    from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerReq

    service = AsyncMock()
    service.answer.side_effect = PermissionServiceUnavailableError()
    with pytest.raises(OpenApiAuthDependencyUnavailableError):
        await answer_knowledge(Request({"type": "http"}), KnowledgeAnswerReq(**BODY), service)


async def test_failure_sets_audit_code():
    from starlette.requests import Request

    from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerReq

    request = Request({"type": "http"})
    service = AsyncMock()
    service.answer.side_effect = KnowledgeAnswerModelError()
    await answer_knowledge(request, KnowledgeAnswerReq(**BODY), service)
    assert request.scope["open_api_error_code"] == 10964
