"""问题列表 sort_by=answered_by_me: 当前用户有效回答过的问题."""

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.qa_expert import ANSWER_STATUS_DELETED, Answer, Expert, Question, QuestionInvite
from bisheng.qa_expert.domain import repositories as repository_module


@pytest.fixture
def answered_by_me_tenant():
    token = set_current_tenant_id(1)
    yield
    current_tenant_id.reset(token)


@pytest.fixture
async def answered_by_me_engine(monkeypatch, answered_by_me_tenant):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for model in (Expert, Question, Answer, QuestionInvite):
            await connection.run_sync(model.__table__.create)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Expert(id=3, user_id=13, expert_name="回答专家"))
        for qid, title in ((2, "待采纳"), (3, "已解决"), (9, "仅他人回答")):
            session.add(
                Question(
                    id=qid,
                    user_id=99,
                    title=title,
                    description="正文",
                    business_domain="设备",
                    question_type="public",
                    answer_count=1,
                    adopt_count=1 if qid == 3 else 0,
                    created_at=datetime(2026, 10, 14),
                )
            )
        session.add(
            Question(
                id=10,
                user_id=99,
                title="仅 expert_id 关联",
                description="正文",
                business_domain="设备",
                question_type="public",
                answer_count=1,
                adopt_count=0,
                created_at=datetime(2026, 10, 14),
            )
        )
        session.add_all(
            [
                Answer(id=1, question_id=2, expert_id=3, user_id=13, expert_name="回答专家", content="答"),
                Answer(id=2, question_id=3, expert_id=3, user_id=13, expert_name="回答专家", content="答"),
                Answer(
                    id=3,
                    question_id=10,
                    expert_id=3,
                    user_id=None,
                    expert_name="回答专家",
                    content="旧数据无 user_id",
                ),
                Answer(
                    id=4,
                    question_id=9,
                    expert_id=99,
                    user_id=88,
                    expert_name="他人",
                    content="他人答",
                ),
                Answer(
                    id=5,
                    question_id=2,
                    expert_id=3,
                    user_id=13,
                    expert_name="回答专家",
                    content="已删",
                    status=ANSWER_STATUS_DELETED,
                ),
            ]
        )
        await session.commit()

    @asynccontextmanager
    async def get_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", get_session)
    yield engine
    await engine.dispose()


async def test_answered_by_me_includes_pending_solved_and_legacy_expert_id(answered_by_me_engine):
    repo = repository_module.QuestionRepository()
    rows, total = await repo.list_all(sort_by="answered_by_me", viewer_user_id=13, viewer_is_admin=False)
    assert total == 3
    assert {row.id for row in rows} == {2, 3, 10}


async def test_answered_by_me_empty_without_viewer(answered_by_me_engine):
    repo = repository_module.QuestionRepository()
    rows, total = await repo.list_all(sort_by="answered_by_me", viewer_user_id=None)
    assert rows == [] and total == 0


async def test_answered_by_me_excludes_deleted_only_answers(answered_by_me_engine):
    """删除态回答不计入; 问题 2 仍有有效回答 id=1."""
    repo = repository_module.QuestionRepository()
    rows, total = await repo.list_all(sort_by="answered_by_me", viewer_user_id=13)
    assert any(row.id == 2 for row in rows)


async def test_http_list_questions_answered_by_me(answered_by_me_engine):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.qa_expert.api import endpoints
    from bisheng.qa_expert.api.router import router
    from bisheng.qa_expert.domain.services import QuestionService

    service = QuestionService()
    service._attach_asker = AsyncMock()
    service.identity_service = SimpleNamespace(preload_for_questions=AsyncMock())
    user = SimpleNamespace(user_id=13, user_name="专家", tenant_id=1, role=None, is_admin=lambda: False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[endpoints.get_question_service] = lambda: service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/qa_experts/questions", params={"sort_by": "answered_by_me"})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["total"] == 3
    assert {item["id"] for item in body["questions"]} == {2, 3, 10}
