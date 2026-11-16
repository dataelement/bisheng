"""Exercise department member filtering against real SQL, without middleware."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.department.domain.services import department_service as service


@pytest.fixture
def _set_tenant_context(tenant_context):
    tenant_context(1)


@pytest.fixture
async def member_search(monkeypatch, _set_tenant_context):
    engine = create_async_engine("sqlite+aiosqlite://")
    schema = [
        """CREATE TABLE user (
            user_id INTEGER PRIMARY KEY, user_name TEXT, external_id TEXT,
            create_time DATETIME, update_time DATETIME,
            "delete" INTEGER DEFAULT 0, disable_source TEXT
        )""",
        """CREATE TABLE user_department (
            id INTEGER PRIMARY KEY, user_id INTEGER, department_id INTEGER,
            is_primary INTEGER, source TEXT DEFAULT 'local', create_time DATETIME
        )""",
        'CREATE TABLE "group" (id INTEGER PRIMARY KEY, group_name TEXT)',
        "CREATE TABLE usergroup (user_id INTEGER, group_id INTEGER)",
        "CREATE TABLE role (id INTEGER PRIMARY KEY, role_name TEXT)",
        "CREATE TABLE userrole (user_id INTEGER, role_id INTEGER)",
    ]
    users = [
        {"id": 1, "name": "李明", "pid": "liwei.xs.extra"},
        {"id": 2, "name": "李威", "pid": "liwei.xs"},
        {"id": 3, "name": "其他部门", "pid": "liwei.xs"},
        {"id": 4, "name": "附属成员", "pid": "liwei.secondary"},
        {"id": 5, "name": "符号账号", "pid": "li_0%"},
        {"id": 6, "name": "literal-li_0%-name", "pid": None},
        {"id": 7, "name": "no wildcard hit", "pid": "liX0more"},
    ]
    users.extend({"id": uid, "name": f"搜索员工{uid}", "pid": f"employee.{uid}"} for uid in range(100, 126))
    async with engine.begin() as conn:
        for ddl in schema:
            await conn.execute(text(ddl))
        await conn.execute(text("INSERT INTO user (user_id, user_name, external_id) VALUES (:id, :name, :pid)"), users)
        await conn.execute(
            text("""INSERT INTO user_department (user_id, department_id, is_primary) VALUES
            (1, 10, 1), (2, 10, 1), (3, 20, 1), (4, 10, 0), (5, 10, 1), (6, 10, 1), (7, 10, 1)
        """)
        )
        await conn.execute(
            text("INSERT INTO user_department (user_id, department_id, is_primary) VALUES (:uid, 10, 1)"),
            [{"uid": uid} for uid in range(100, 126)],
        )

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(service, "get_async_db_session", session_factory)
    monkeypatch.setattr(service, "_get_dept_and_check_permission", AsyncMock(return_value=SimpleNamespace(id=10)))
    monkeypatch.setattr(service.DepartmentService, "_aget_department_admin_user_ids", AsyncMock(return_value=[]))

    async def search(keyword, *, page=1, limit=20, is_primary=None, focus_user_id=None):
        return await service.DepartmentService.aget_members(
            "BS@department",
            page,
            limit,
            keyword,
            SimpleNamespace(user_id=99, is_global_super=True),
            is_primary=is_primary,
            **({"focus_user_id": focus_user_id} if focus_user_id is not None else {}),
        )

    yield search
    await engine.dispose()


@pytest.mark.parametrize(
    ("keyword", "expected_ids"),
    [
        ("liwei.xs", [2, 1]),
        ("  liwei.xs  ", [2, 1]),
        ("李", [1, 2]),
        ("威", [2]),
        ("LIWEI", []),
        ("wei.xs", []),
        ("li_0%", [5, 6]),
    ],
)
async def test_member_search_accepts_person_id_and_keeps_name_contains(member_search, keyword, expected_ids):
    result = await member_search(keyword)
    assert [row["user_id"] for row in result["data"]] == expected_ids
    assert result["total"] == len(expected_ids)


async def test_member_search_keeps_department_relation_filter_and_pagination(member_search):
    first = await member_search("liwei", limit=1)
    second = await member_search("liwei", page=2, limit=1)
    empty_page = await member_search("liwei", page=9, limit=1)
    secondary = await member_search("liwei", is_primary=0)
    primary = await member_search("liwei", is_primary=1)

    assert first["total"] == second["total"] == empty_page["total"] == 3
    assert [row["user_id"] for row in first["data"]] == [1]
    assert [row["user_id"] for row in second["data"]] == [2]
    assert empty_page["data"] == []
    assert [row["user_id"] for row in secondary["data"]] == [4]
    assert [row["user_id"] for row in primary["data"]] == [1, 2]


async def test_exact_person_id_is_on_first_page(member_search):
    result = await member_search("liwei.xs", limit=1)
    assert result["total"] == 2
    assert result["data"][0]["user_id"] == 2


async def test_selected_member_is_first_even_when_name_matches_span_multiple_pages(member_search):
    result = await member_search("搜索", focus_user_id=125)
    assert result["total"] == 26
    assert len(result["data"]) == 20
    assert result["data"][0]["user_id"] == 125


async def test_focused_member_cannot_bypass_department_or_keyword_filters(member_search):
    result = await member_search("李", focus_user_id=3)
    assert [row["user_id"] for row in result["data"]] == [1, 2]
    result = await member_search("liwei.xs", focus_user_id=5)
    assert [row["user_id"] for row in result["data"]] == [2, 1]


async def test_blank_keyword_returns_department_members(member_search):
    result = await member_search(" \t ", limit=100)
    assert result["total"] == 32
    assert {1, 2, 4, 5, 6, 7}.issubset({row["user_id"] for row in result["data"]})
    assert 3 not in {row["user_id"] for row in result["data"]}


async def test_oversized_keyword_is_rejected(member_search):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await member_search("x" * 256)
    assert exc.value.status_code == 422


async def test_member_endpoint_returns_located_user_on_first_page(member_search):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.department.api.endpoints.department_member import router

    app = FastAPI()
    app.include_router(router, prefix="/departments")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=99, is_global_super=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/departments/BS@department/members",
            params={"keyword": "搜索", "focus_user_id": 125},
        )
        assert response.status_code == 200
        result = response.json()["data"]
        assert result["total"] == 26
        assert result["data"][0]["user_id"] == 125

        invalid = await client.get("/departments/BS@department/members", params={"focus_user_id": 0})
        assert invalid.status_code == 422
