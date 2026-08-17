# ruff: noqa: RUF002
"""T025：回答/采纳/评论 API。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.qa_expert import QaExpertAdoptLimitError, QaExpertCommentNotAllowedError
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router


def _user():
    return SimpleNamespace(
        user_id=8,
        user_name="expert",
        tenant_id=1,
        is_admin=lambda: False,
        role=None,
        is_global_super=False,
    )


def _app(*, answer=None, question=None, comment=None):
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        from fastapi.responses import JSONResponse

        return JSONResponse({"status_code": exc.code, "status_message": exc.message, "data": None})

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = _user
    if answer is not None:
        app.dependency_overrides[endpoints.get_answer_service] = lambda: answer
    if question is not None:
        app.dependency_overrides[endpoints.get_question_service] = lambda: question
    if comment is not None:
        app.dependency_overrides[endpoints.get_comment_service] = lambda: comment
    return app


def test_create_answer_and_adopt():
    answer_svc = SimpleNamespace(create_answer=AsyncMock(return_value={"id": 2, "question_id": 1}))
    question_svc = SimpleNamespace(
        adopt_answer=AsyncMock(return_value={"id": 1, "adopt_count": 1, "display_status": "solved"})
    )
    client = TestClient(_app(answer=answer_svc, question=question_svc))
    resp = client.post("/api/v1/qa_experts/answers", json={"question_id": 1, "content": "答"})
    assert resp.json()["status_code"] == 200
    adopted = client.post("/api/v1/qa_experts/questions/1/adopt", json={"answer_id": 2})
    assert adopted.json()["status_code"] == 200


def test_fourth_adopt_returns_18304():
    question_svc = SimpleNamespace(adopt_answer=AsyncMock(side_effect=QaExpertAdoptLimitError()))
    client = TestClient(_app(question=question_svc))
    resp = client.post("/api/v1/qa_experts/questions/1/adopt", json={"answer_id": 9})
    assert resp.json()["status_code"] == 18304


def test_comment_without_answer_returns_18309():
    comment_svc = SimpleNamespace(create_comment=AsyncMock(side_effect=QaExpertCommentNotAllowedError()))
    client = TestClient(_app(comment=comment_svc))
    resp = client.post(
        "/api/v1/qa_experts/comments",
        json={"answer_id": 2, "content": "评", "question_id": 1},
    )
    assert resp.json()["status_code"] == 18309
