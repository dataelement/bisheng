# ruff: noqa: RUF002
"""T023：问题 API TestClient。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.qa_expert import QaExpertQuestionAccessDeniedError
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router


def _user(*, user_id=1, admin=False, role=None, super_admin=False):
    return SimpleNamespace(
        user_id=user_id,
        user_name=f"u{user_id}",
        tenant_id=1,
        is_admin=lambda: admin,
        role=role,
        is_global_super=super_admin,
    )


def _app(question_service, user):
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.dependency_overrides[endpoints.get_question_service] = lambda: question_service
    return app


def test_create_and_get_question_related_docs_accessible_fields():
    svc = SimpleNamespace()
    created = {"id": 11, "title": "公开题", "question_type": "public"}
    detail = SimpleNamespace(
        id=11,
        title="公开题",
        description="正文",
        related_docs="3-8",
        related_doc_views=[
            {
                "id": "3-8",
                "space_id": 3,
                "file_id": 8,
                "title": "规程",
                "accessible": False,
                "unavailable_reason": "forbidden",
            }
        ],
        display_status="unanswered",
        capabilities={"can_answer": False, "visible": True},
        question_type="public",
        content_locked=0,
        model_dump=lambda: {
            "id": 11,
            "title": "公开题",
            "description": "正文",
            "related_docs": "3-8",
        },
    )
    svc.create_question = AsyncMock(return_value=created)
    svc.get_question_detail = AsyncMock(return_value=detail)
    svc.list_questions = AsyncMock(return_value=([created], 1))
    with patch("bisheng.qa_expert.api.endpoints.check_question_content"):
        client = TestClient(_app(svc, _user()))
        created_resp = client.post(
            "/api/v1/qa_experts/questions",
            json={"title": "公开题", "description": "正文", "business_domain": "steel", "question_type": "public"},
        )
    assert created_resp.status_code == 200
    assert created_resp.json()["status_code"] == 200
    detail_resp = client.get("/api/v1/qa_experts/questions/11")
    body = detail_resp.json()["data"]
    docs = body.get("related_docs") or body.get("related_doc_views")
    assert docs[0]["accessible"] is False
    assert docs[0]["unavailable_reason"] == "forbidden"
    assert body["description"] == "正文"
    assert body["capabilities"]["can_answer"] is False
    assert body["display_status"] == "unanswered"


def test_get_question_detail_includes_capabilities_without_related_docs():
    """无关联文档时也必须下发 capabilities，否则详情页没有回答框/采纳。"""
    svc = SimpleNamespace()
    detail = SimpleNamespace(
        id=12,
        title="无文档",
        description="正文",
        related_docs=None,
        related_doc_views=[],
        display_status="unanswered",
        capabilities={"can_answer": True, "visible": True, "can_adopt": True},
        question_type="public",
        content_locked=0,
        model_dump=lambda: {
            "id": 12,
            "title": "无文档",
            "description": "正文",
            "related_docs": None,
            "content_locked": 0,
        },
    )
    svc.get_question_detail = AsyncMock(return_value=detail)
    client = TestClient(_app(svc, _user()))
    body = client.get("/api/v1/qa_experts/questions/12").json()["data"]
    assert body["capabilities"]["can_answer"] is True
    assert body["capabilities"]["can_adopt"] is True
    assert body["display_status"] == "unanswered"
    assert body["content_locked"] == 0


def test_directed_detail_returns_18301():
    svc = SimpleNamespace()
    svc.get_question_detail = AsyncMock(side_effect=QaExpertQuestionAccessDeniedError())
    client = TestClient(_app(svc, _user(user_id=99)))
    resp = client.get("/api/v1/qa_experts/questions/9")
    assert resp.json()["status_code"] == 18301


def test_list_questions_redacts_anonymous_created_by():
    """列表 JSON 匿名题不得下发 created_by 真名。"""
    svc = SimpleNamespace()
    row = SimpleNamespace(
        id=21,
        title="匿名公开",
        created_by="gzx01",
        asker={"display_name": "匿名同事A", "anonymous": True, "avatar_url": None},
        display_status="unanswered",
        model_dump=lambda: {
            "id": 21,
            "title": "匿名公开",
            "created_by": "gzx01",
            "business_domain": "营销",
        },
    )
    svc.list_questions = AsyncMock(return_value=([row], 1))
    client = TestClient(_app(svc, _user(user_id=99)))
    body = client.get("/api/v1/qa_experts/questions").json()["data"]
    hit = body["questions"][0]
    assert hit["created_by"] == "匿名同事A"
    assert hit["asker"]["display_name"] == "匿名同事A"
    assert hit["asker"]["anonymous"] is True
    assert "real_name" not in hit["asker"]


def test_list_questions_includes_latest_answer_preview():
    """列表 JSON 要把 latest_answer 一并打出，供卡片预览。"""
    svc = SimpleNamespace()
    row = SimpleNamespace(
        id=21,
        title="有回答",
        latest_answer={"id": 9, "excerpt": "最新答", "expert_name": "gzx001", "adopted": True, "anonymous": False},
        display_status="pending_adopt",
        model_dump=lambda: {"id": 21, "title": "有回答", "answer_count": 1},
    )
    svc.list_questions = AsyncMock(return_value=([row], 1))
    client = TestClient(_app(svc, _user(user_id=99)))
    body = client.get("/api/v1/qa_experts/questions").json()["data"]
    hit = body["questions"][0]
    assert hit["latest_answer"]["excerpt"] == "最新答"
    assert hit["latest_answer"]["expert_name"] == "gzx001"
    assert hit["latest_answer"]["adopted"] is True
