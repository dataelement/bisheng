from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.department import Department
from bisheng.database.models.qa_expert import Expert
from bisheng.qa_expert.domain import repositories as repository_module
from bisheng.qa_expert.domain.services import ExpertService


@pytest.fixture()
async def expert_engine(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Department.__table__.create)
        await connection.run_sync(Expert.__table__.create)

    @asynccontextmanager
    async def get_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_async_db_session", get_session)
    yield engine
    await engine.dispose()


async def _seed_experts(engine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Department(id=101, dept_id="quality", name="质量管理部", short_name="质量"),
                Department(id=102, dept_id="equipment", name="设备管理部", short_name="设备"),
                Department(id=103, dept_id="analysis", name="分析检测部", short_name=None),
                Expert(
                    id=1,
                    user_id=11,
                    expert_name="甲专家",
                    introduction="质量专家",
                    depart_ment="101",
                    job_family="制造技术族",
                    job_category="质量技术类",
                    position="质量检测",
                    major="首席工程师",
                    answer_count=2,
                    adoption_count=1,
                    vote_count=2,
                ),
                Expert(
                    id=2,
                    user_id=12,
                    expert_name="乙专家",
                    introduction="设备专家",
                    depart_ment="102",
                    job_family="技能操作族",
                    job_category="设备技能类",
                    position="精密点检",
                    major="首席技师",
                    answer_count=10,
                    adoption_count=0,
                    vote_count=0,
                ),
                Expert(
                    id=3,
                    user_id=13,
                    expert_name="丙专家",
                    introduction="质量分析",
                    depart_ment="103",
                    job_family="制造技术族",
                    job_category="质量技术类",
                    position="化学分析",
                    major="首席工程师",
                    answer_count=1,
                    adoption_count=3,
                    vote_count=1,
                ),
            ]
        )
        await session.commit()


async def test_repository_combines_search_filters_and_expert_score_sort(
    expert_engine,
) -> None:
    await _seed_experts(expert_engine)

    experts, total = await repository_module.ExpertRepository().list_all(
        keyword="质量",
        job_family="制造技术族",
        job_category="质量技术类",
        major="首席工程师",
        sort_by="expert_score",
        sort_order="desc",
        skip=0,
        limit=10,
    )

    assert total == 2
    assert [expert.expert_name for expert in experts] == ["丙专家", "甲专家"]

    department_experts, department_total = await repository_module.ExpertRepository().list_all(
        keyword="质量",
        department_id="101",
        job_family="制造技术族",
        sort_by="expert_score",
        sort_order="desc",
        skip=0,
        limit=10,
    )

    assert department_total == 1
    assert [expert.expert_name for expert in department_experts] == ["甲专家"]

    short_name_experts, short_name_total = await repository_module.ExpertRepository().list_all(
        keyword="设备",
        sort_by="expert_score",
        sort_order="desc",
        skip=0,
        limit=10,
    )

    assert short_name_total == 1
    assert [expert.expert_name for expert in short_name_experts] == ["乙专家"]


async def test_repository_returns_distinct_filter_options(expert_engine) -> None:
    await _seed_experts(expert_engine)

    options = await repository_module.ExpertRepository().list_filter_options()

    assert options == {
        "department_ids": ["101", "102", "103"],
        "job_families": ["制造技术族", "技能操作族"],
        "job_categories": ["设备技能类", "质量技术类"],
        "positions": ["化学分析", "精密点检", "质量检测"],
        "majors": ["首席工程师", "首席技师"],
    }


async def test_service_sorts_department_names_before_paginating(monkeypatch) -> None:
    service = ExpertService()
    service.repository = AsyncMock()
    service.repository.list_all.return_value = (
        [
            Expert(
                id=1,
                user_id=11,
                expert_name="甲专家",
                depart_ment="101",
                answer_count=2,
                adoption_count=1,
                vote_count=2,
            ),
            Expert(
                id=2,
                user_id=12,
                expert_name="乙专家",
                depart_ment="102",
                answer_count=1,
                adoption_count=3,
                vote_count=1,
            ),
            Expert(
                id=3,
                user_id=13,
                expert_name="无部门专家",
                depart_ment=None,
                answer_count=0,
                adoption_count=0,
                vote_count=0,
            ),
        ],
        3,
    )
    monkeypatch.setattr(
        "bisheng.qa_expert.domain.services.DepartmentDao.aget_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=101, name="质量部", short_name="质量"),
                SimpleNamespace(id=102, name="设备部", short_name="设备"),
            ]
        ),
    )
    monkeypatch.setattr(
        "bisheng.qa_expert.domain.services.UserDao.aget_user_by_ids",
        AsyncMock(return_value=[]),
    )
    service._build_dict_key_maps = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "job_family": {},
            "job_category": {},
            "position": {},
            "major": {},
        }
    )

    experts, total = await service.list_experts(
        sort_by="department",
        sort_order="asc",
        skip=1,
        limit=1,
    )

    assert total == 3
    assert [expert["expert_name"] for expert in experts] == ["甲专家"]
    assert experts[0]["expert_score"] == 11
    assert experts[0]["depart_ment"] == "质量部"
    assert experts[0]["department_display_name"] == "质量"
    service.repository.list_all.assert_awaited_once_with(
        keyword=None,
        department_id=None,
        job_family=None,
        job_category=None,
        position=None,
        major=None,
        sort_by="department",
        sort_order="asc",
        skip=0,
        limit=None,
        answer_desc=None,
        adoption_desc=None,
        vote_desc=None,
        status=None,
    )


async def test_service_maps_department_filter_options(monkeypatch) -> None:
    service = ExpertService()
    service.repository = AsyncMock()
    service.repository.list_filter_options.return_value = {
        "department_ids": ["102", "101"],
        "job_families": [],
        "job_categories": [],
        "positions": [],
        "majors": [],
    }
    monkeypatch.setattr(
        "bisheng.qa_expert.domain.services.DepartmentDao.aget_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=102, name="设备部", short_name="设备"),
                SimpleNamespace(id=101, name="质量部", short_name=None),
            ]
        ),
    )

    options = await service.list_filter_options()

    assert options["departments"] == [
        {"id": "102", "name": "设备部", "short_name": "设备", "display_name": "设备"},
        {"id": "101", "name": "质量部", "short_name": None, "display_name": "质量部"},
    ]


async def test_repository_status_filter_excludes_disabled(expert_engine) -> None:
    await _seed_experts(expert_engine)
    async with AsyncSession(expert_engine, expire_on_commit=False) as session:
        expert = await session.get(Expert, 2)
        expert.status = 0
        session.add(expert)
        await session.commit()

    _all_rows, all_total = await repository_module.ExpertRepository().list_all(skip=0, limit=10)
    active_rows, active_total = await repository_module.ExpertRepository().list_all(
        skip=0,
        limit=10,
        status=1,
    )

    assert all_total == 3
    assert active_total == 2
    assert {row.expert_name for row in active_rows} == {"甲专家", "丙专家"}
