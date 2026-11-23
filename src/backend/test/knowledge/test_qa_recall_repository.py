"""Real SQLite parent binding and unscoped-recall containment regressions."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.domain.repositories import qa_recall_repository as repository


@pytest.fixture
def storage(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (ChatMessage, MessageSession, RecallChunk):
        model.__table__.create(engine)
    with bypass_tenant_filter(), Session(engine) as session:
        session.add_all(
            [
                MessageSession(chat_id="own", flow_id="app", flow_type=10, user_id=7, tenant_id=1),
                MessageSession(chat_id="other", flow_id="app", flow_type=10, user_id=8, tenant_id=2),
                ChatMessage(
                    id=1,
                    chat_id="own",
                    flow_id="app",
                    user_id=7,
                    tenant_id=1,
                    message="answer",
                    is_bot=1,
                    category="answer",
                    type="answer",
                ),
                ChatMessage(
                    id=2,
                    chat_id="other",
                    flow_id="app",
                    user_id=8,
                    tenant_id=2,
                    message="answer",
                    is_bot=1,
                    category="answer",
                    type="answer",
                ),
                RecallChunk(message_id=1, chat_id="own", keywords='["own"]', file_id=9),
                RecallChunk(message_id=1, chat_id="other", keywords='["poison"]', file_id=99),
                RecallChunk(message_id=2, chat_id="other", keywords='["foreign"]', file_id=99),
            ]
        )
        session.commit()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(repository, "get_sync_db_session", factory)
    tid = current_tenant_id.set(1)
    try:
        yield repository.QaRecallRepository
    finally:
        current_tenant_id.reset(tid)
        engine.dispose()


def test_real_parent_and_recall_require_both_identifiers(storage):
    message, parent = storage.parent(1)
    assert (message.user_id, parent.user_id, parent.chat_id) == (7, 7, "own")
    chunks = storage.chunks(1, parent.chat_id)
    assert [row.keywords for row in chunks] == ['["own"]']


async def test_service_rejects_real_foreign_parent_even_without_orm_events(storage):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from bisheng.knowledge.domain.services.qa_recall_service import QaRecallService

    with pytest.raises(HTTPException) as exc:
        await QaRecallService.keywords(SimpleNamespace(user_id=8, tenant_id=1), 2)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("user_id,message_id,expected", [(7, 1, 200), (9, 1, 403), (8, 2, 404)])
async def test_http_endpoint_service_and_real_repository(storage, monkeypatch, user_id, message_id, expected):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.knowledge.api.endpoints import qa
    from bisheng.knowledge.domain.services import qa_recall_service

    app = FastAPI()
    app.include_router(qa.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=user_id, tenant_id=1)
    app.add_exception_handler(
        UnAuthorizedError, lambda request, exc: JSONResponse(status_code=403, content={"detail": "Forbidden"})
    )
    monkeypatch.setattr(
        qa_recall_service.AuditLogService, "assert_session_in_audit_scope", AsyncMock(side_effect=UnAuthorizedError())
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/qa/keyword", params={"message_id": message_id})
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["data"] == ["own"]
    else:
        assert "own" not in response.text and "foreign" not in response.text
