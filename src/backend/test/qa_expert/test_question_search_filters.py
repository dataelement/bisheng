"""搜索筛选使用隔离 SQLite 执行真实 ORM 查询, 不连接业务数据库。"""

from contextlib import asynccontextmanager
from datetime import date, datetime
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.config.multi_tenant import MultiTenantConf
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.qa_expert import Answer, Expert, Question, QuestionInvite
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router
from bisheng.qa_expert.domain import repositories as repository_module
from bisheng.qa_expert.domain.services import ExpertService, QuestionService


@pytest.fixture
def search_tenant():
    token = set_current_tenant_id(1)
    yield
    current_tenant_id.reset(token)


@pytest.fixture
async def search_engine(monkeypatch, search_tenant):
    monkeypatch.setattr(
        import_module("bisheng.common.services.config_service"),
        "settings",
        SimpleNamespace(multi_tenant=MultiTenantConf(enabled=False)),
    )
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for model in (Expert, Question, Answer, QuestionInvite):
            await connection.run_sync(model.__table__.create)

    @asynccontextmanager
    async def get_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", get_session)
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                Expert(id=1, user_id=11, expert_name="受邀甲", depart_ment="100", major="rolling", position="工程师"),
                Expert(id=2, user_id=12, expert_name="受邀乙", depart_ment="200", major="maintenance", status=0),
                Expert(id=3, user_id=13, expert_name="回答专家专属"),
                Expert(id=4, user_id=14, expert_name="匿名真实姓名"),
            ]
        )
        for qid in range(1, 10):
            session.add(
                Question(
                    id=qid,
                    user_id=99 if qid == 5 else 77,
                    title=f"问题{qid}",
                    description="正文专属" if qid == 1 else "正文",
                    business_domain="设备",
                    question_type="directed" if qid == 4 else "public",
                    answer_count=2 if qid == 2 else (1 if qid in (3, 7) else 0),
                    adopt_count=1 if qid == 7 else 0,
                    created_at=datetime(2026, 10, 15) if qid == 6 else datetime(2026, 10, 14, 23, 59, 59),
                )
            )
        session.add(
            Question(id=99, tenant_id=2, user_id=77, title="跨租户", description="正文专属", business_domain="设备")
        )
        session.add_all(
            [
                Answer(id=1, question_id=2, expert_id=3, user_id=13, expert_name="回答专家专属", content="答案专属"),
                Answer(id=2, question_id=2, expert_id=3, user_id=13, expert_name="回答专家专属", content="答案专属"),
                Answer(
                    id=3,
                    question_id=3,
                    expert_id=4,
                    user_id=14,
                    expert_name="匿名真实姓名",
                    anonymous=1,
                    content="匿名正文",
                ),
                Answer(id=4, question_id=8, user_id=15, expert_name="已删除专家", content="删除答案专属", status=3),
            ]
        )
        for qid, eid in [(1, 1), (2, 2), (4, 1), (5, 1), (7, 1), (7, 2)]:
            session.add(QuestionInvite(question_id=qid, expert_id=eid, user_id=10 + eid))
        await session.commit()
    yield engine
    await engine.dispose()


@pytest.mark.parametrize(
    ("keyword", "ids"),
    [
        ("正文专属", [1]),
        ("答案专属", [2]),
        ("回答专家专属", [2]),
        ("受邀乙", [7, 2]),
        ("删除答案专属", []),
        ("匿名真实姓名", []),
        ("定向", []),
    ],
)
async def test_keyword_search_content_experts_and_anonymous(search_engine, keyword, ids):
    rows, total = await repository_module.QuestionRepository().list_all(keyword=keyword, viewer_user_id=99)
    assert [row.id for row in rows] == ids
    assert total == len(ids)


async def test_query_filters_before_paging_and_counts_current_tenant(search_engine):
    repo = repository_module.QuestionRepository()
    rows, total = await repo.list_all(
        viewer_user_id=99, asked_from=date(2026, 10, 14), asked_to=date(2026, 10, 14), invited_expert_ids=[1], limit=1
    )
    assert total == 3
    assert [row.id for row in rows] == [7]
    rows, total = await repo.list_all(
        viewer_user_id=99, asked_to=date(2026, 10, 14), invited_expert_ids=[1], display_status="solved"
    )
    assert total == 1 and [row.id for row in rows] == [7]
    rows, total = await repo.list_all(viewer_user_id=99, invited_expert_ids=[], keyword="问题")
    assert rows == [] and total == 0
    rows, total = await repo.list_all(viewer_user_id=99, keyword="正文专属", limit=1, skip=1)
    assert rows == [] and total == 1


async def test_unresolved_and_solved_hide_directed_from_others_admin_sees_all(search_engine):
    """未解决/已解决与默认列表同一可见性: 外人看不到定向题, 专家库管理员看全部."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    async with AsyncSession(search_engine, expire_on_commit=False) as session:
        session.add(
            Question(
                id=40,
                user_id=77,
                title="定向已解决",
                description="正文",
                business_domain="设备",
                question_type="directed",
                answer_count=1,
                adopt_count=1,
                created_at=datetime(2026, 10, 14),
            )
        )
        await session.commit()
    repo = repository_module.QuestionRepository()
    outsider, _ = await repo.list_all(viewer_user_id=99, display_status="unresolved", viewer_is_admin=False)
    assert 4 not in {row.id for row in outsider}
    invited, _ = await repo.list_all(viewer_user_id=11, display_status="unresolved", viewer_is_admin=False)
    assert 4 in {row.id for row in invited}
    solved_out, _ = await repo.list_all(viewer_user_id=99, display_status="solved", viewer_is_admin=False)
    assert 40 not in {row.id for row in solved_out}
    admin_unresolved, _ = await repo.list_all(viewer_user_id=99, display_status="unresolved", viewer_is_admin=True)
    admin_solved, _ = await repo.list_all(viewer_user_id=99, display_status="solved", viewer_is_admin=True)
    assert 4 in {row.id for row in admin_unresolved}
    assert 40 in {row.id for row in admin_solved}


async def test_list_question_type_filter_public_and_directed(search_engine):
    """question_type 在仓储层过滤; 与既有可见性规则叠加."""
    repo = repository_module.QuestionRepository()
    public_rows, public_total = await repo.list_all(viewer_user_id=99, question_type="public", viewer_is_admin=False)
    assert 4 not in {row.id for row in public_rows}
    assert public_total >= len(public_rows)
    assert all(getattr(row, "question_type", "public") != "directed" for row in public_rows)

    directed_rows, directed_total = await repo.list_all(
        viewer_user_id=11, question_type="directed", viewer_is_admin=False
    )
    assert {row.id for row in directed_rows} == {4}
    assert directed_total == 1

    outsider_directed, outsider_total = await repo.list_all(
        viewer_user_id=99, question_type="directed", viewer_is_admin=False
    )
    assert outsider_directed == [] and outsider_total == 0


async def test_directed_visibility_and_admin_anonymous_name(search_engine):
    repo = repository_module.QuestionRepository()
    rows, total = await repo.list_all(viewer_user_id=11, keyword="问题4")
    assert total == 1 and rows[0].id == 4
    rows, total = await repo.list_all(viewer_user_id=99, keyword="问题4", invited_expert_ids=[1])
    assert rows == [] and total == 0
    rows, total = await repo.list_all(viewer_user_id=99, keyword="匿名真实姓名", viewer_is_admin=True)
    assert total == 1 and rows[0].id == 3


async def test_person_filters_same_invited_expert_and_dict_aliases(search_engine):
    svc = ExpertService()
    svc._load_expert_display_departments = AsyncMock(
        return_value={
            1: SimpleNamespace(id=100),
            2: SimpleNamespace(id=200),
            3: None,
            4: None,
        }
    )
    svc.repository.list_department_sources = AsyncMock(return_value=[])
    svc._expand_career_filters = AsyncMock(
        return_value={
            "major": ["major-key", "rolling"],
            "position": None,
            "job_family": None,
            "job_category": None,
        }
    )
    ids = await svc.find_filter_expert_ids(department_id="100", major="major-key")
    assert ids == [1]
    rows, total = await repository_module.QuestionRepository().list_all(viewer_user_id=99, invited_expert_ids=ids)
    assert total == 3 and {row.id for row in rows} == {1, 5, 7}
    ids = await svc.find_filter_expert_ids(department_id="200", major="major-key")
    assert ids == []


async def test_literal_wildcard_is_not_match_all(search_engine):
    repo = repository_module.QuestionRepository()
    rows, total = await repo.list_all(viewer_user_id=99, keyword="%")
    assert rows == [] and total == 0


async def test_http_search_filters_query_real_database(search_engine):
    service = QuestionService()
    # 用户展示依赖独立账号域; 核心查询和邀请关系使用真实仓储。
    service._attach_asker = AsyncMock()
    service.identity_service = SimpleNamespace(preload_for_questions=AsyncMock())
    user = SimpleNamespace(user_id=99, user_name="读者", tenant_id=1, role=None, is_admin=lambda: False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[endpoints.get_question_service] = lambda: service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        params = {"invited_expert_id": 1, "asked_from": "2026-10-14", "asked_to": "2026-10-14", "page_size": 1}
        first = await client.get("/api/v1/qa_experts/questions", params=params)
        second = await client.get("/api/v1/qa_experts/questions", params={**params, "page": 2})
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["data"]["total"] == second.json()["data"]["total"] == 3
        assert first.json()["data"]["questions"][0]["id"] == 7
        assert second.json()["data"]["questions"][0]["id"] == 5
        response = await client.get("/api/v1/qa_experts/questions", params={"keyword": "答案专属"})
        assert response.json()["data"]["total"] == 1
        assert response.json()["data"]["questions"][0]["id"] == 2
        invalid = await client.get("/api/v1/qa_experts/questions", params={"question_type": "secret"})
        assert invalid.status_code == 422
