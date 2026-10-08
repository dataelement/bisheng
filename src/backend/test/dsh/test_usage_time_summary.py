"""Time-range DSH usage aggregation and management authorization."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.services.admin import DshManagementService
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.user.domain.models.user import User
from test.dsh.test_usage_repository import usage_db  # noqa: F401


def call(request_id, *, tenant=2, user=20, started_at, status, usage=None):
    input_tokens, output_tokens = usage or (None, None)
    return DshModelCall(
        request_id=request_id,
        tenant_id=tenant,
        user_id=user,
        seat_id="seat",
        session_id="session",
        grant_version=1,
        model_id=4,
        usage_month="2026-09",
        policy_version=1,
        event_version=2,
        quota_epoch=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=None if usage is None else input_tokens + output_tokens,
        status=status,
        usage_source=None if usage is None else "PROVIDER",
        started_at=started_at,
        ended_at=None if status in {"RUNNING", "USAGE_UNKNOWN"} else started_at + timedelta(seconds=2),
    )


@pytest.fixture
def overview_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'usage-overview.db'}")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            User.__table__,
            Department.__table__,
            UserTenant.__table__,
            UserDepartment.__table__,
            DshModelCall.__table__,
        ],
    )
    with Session(engine) as session, session.begin(), profile_scope(2):
        session.add(Tenant(id=2, tenant_code="tenant-2", tenant_name="测试组织"))
        session.add_all(
            [
                User(user_id=20, user_name="alice", password="x"),
                User(user_id=21, user_name="bob", password="x"),
                Department(id=10, dept_id="root", name="总部", tenant_id=2, path="/10/"),
                Department(id=11, dept_id="child", name="研发部", tenant_id=2, parent_id=10, path="/10/11/"),
                UserTenant(id=1, user_id=20, tenant_id=2, status="active", is_active=1),
                UserTenant(id=2, user_id=21, tenant_id=2, status="active", is_active=1),
                UserDepartment(id=1, user_id=20, department_id=11, is_primary=1),
                UserDepartment(id=2, user_id=21, department_id=10, is_primary=1),
                call("alice-call", user=20, started_at=datetime(2026, 9, 9), status="SUCCEEDED", usage=(10, 5)),
                call("bob-call", user=21, started_at=datetime(2026, 9, 9, 1), status="FAILED"),
            ]
        )
    yield engine
    engine.dispose()


def test_usage_overview_aggregates_department_scope_and_user_rows(overview_db):
    from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository

    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = start + timedelta(days=1)
    with Session(overview_db) as session, profile_scope(2):
        result = DshAdminQueryRepository(session).usage_overview(
            start_at=start,
            end_at=end,
            after_user_id=0,
            limit=20,
            keyword="",
            department_ids=[10, 11],
            selected_department_id=10,
        )

    assert result["department_id"] == 10
    assert result["totals"]["message_count"] == 1
    assert result["totals"]["total_tokens"] == 15
    assert [(item["user_name"], item["department_name"]) for item in result["items"]] == [
        ("alice", "研发部"),
        ("bob", "总部"),
    ]
    assert result["items"][1]["metrics"]["message_count"] == 0


def test_usage_summary_counts_only_platform_accounted_requests(usage_db):  # noqa: F811
    with Session(usage_db) as session, session.begin():
        with profile_scope(2):
            session.add_all(
                [
                    call(
                        "successful",
                        started_at=datetime(2026, 9, 9, 0, 15),
                        status="SUCCEEDED",
                        usage=(10, 5),
                    ),
                    call(
                        "failed",
                        started_at=datetime(2026, 9, 9, 1, 10),
                        status="FAILED",
                        usage=(2, 3),
                    ),
                    call(
                        "usage-unknown",
                        started_at=datetime(2026, 9, 9, 1, 20),
                        status="USAGE_UNKNOWN",
                    ),
                    call(
                        "other-user",
                        user=21,
                        started_at=datetime(2026, 9, 9, 1, 30),
                        status="USAGE_UNKNOWN",
                    ),
                ]
            )
        with profile_scope(3):
            session.add(
                call(
                    "foreign-tenant",
                    tenant=3,
                    started_at=datetime(2026, 9, 9, 1, 40),
                    status="SUCCEEDED",
                    usage=(100, 100),
                )
            )

    from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository

    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = start + timedelta(hours=3)
    with Session(usage_db) as session, profile_scope(2):
        summary = DshAdminQueryRepository(session).usage_time_summary(
            20,
            start_at=start,
            end_at=end,
            granularity="hour",
        )
        unknown_only = DshAdminQueryRepository(session).usage_time_summary(
            21,
            start_at=start,
            end_at=end,
            granularity="hour",
        )
        empty = DshAdminQueryRepository(session).usage_time_summary(
            99,
            start_at=start,
            end_at=end,
            granularity="hour",
        )

    assert summary["timezone"] == "Asia/Shanghai" and summary["granularity"] == "hour"
    assert summary["totals"] == {
        "message_count": 2,
        "qa_count": 1,
        "failed_count": 1,
        "cancelled_count": 0,
        "running_count": 0,
        "usage_unknown_count": 0,
        "recorded_usage_count": 2,
        "missing_usage_count": 0,
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }
    assert [point["message_count"] for point in summary["points"]] == [1, 1, 0]
    assert summary["points"][0]["start_at"] == "2026-09-09T08:00:00+08:00"
    assert summary["points"][1]["total_tokens"] == 5
    assert summary["points"][2]["total_tokens"] == 0
    assert unknown_only["totals"]["message_count"] == 0
    assert unknown_only["totals"]["total_tokens"] == 0
    assert empty["totals"]["message_count"] == 0 and empty["totals"]["total_tokens"] == 0


def test_department_time_series_covers_full_scope_and_deduplicates_members(overview_db):
    from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository

    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = start + timedelta(days=1)
    with Session(overview_db) as session, session.begin(), profile_scope(2):
        session.add(UserDepartment(id=3, user_id=20, department_id=10, is_primary=0))
    with Session(overview_db) as session, profile_scope(2):
        repository = DshAdminQueryRepository(session)
        query = {
            "start_at": start,
            "end_at": end,
            "after_user_id": 0,
            "limit": 1,
            "keyword": "",
            "department_ids": [10, 11],
            "selected_department_id": 10,
            "include_summary": True,
        }
        first = repository.usage_overview(**query)
        second = repository.usage_overview(**{**query, "after_user_id": 20})
        child = repository.usage_overview(**{**query, "department_ids": [11], "selected_department_id": 11})
    assert first["has_more"] and len(first["items"]) == 1
    assert first["summary"] == second["summary"]
    assert first["summary"]["totals"] == first["totals"]
    assert first["summary"]["totals"]["message_count"] == 1
    assert first["summary"]["totals"]["total_tokens"] == 15
    assert first["summary"]["granularity"] == "hour"
    assert len(first["summary"]["points"]) == 24
    assert first["summary"]["points"][1]["total_tokens"] == 0
    assert child["summary"]["totals"]["message_count"] == 1
    with Session(overview_db) as session, profile_scope(3):
        foreign = DshAdminQueryRepository(session).usage_overview(**query)
    assert foreign["summary"]["totals"]["message_count"] == 0


async def test_usage_summary_service_authorizes_target_and_selects_granularity():
    authorize = AsyncMock(return_value=({}, 2))
    reader = AsyncMock(return_value={"message_count": 0})
    service = DshManagementService(
        repository_scope=None,
        gateway=None,
        authorize=authorize,
        profiles=None,
        policy=None,
        policy_view=None,
        now=None,
        usage_summary_view=reader,
    )
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = start + timedelta(hours=48)

    with profile_scope(1):
        assert await service.usage_summary(90, 20, start_at=start, end_at=end, tenant_id=2) == {"message_count": 0}
    authorize.assert_awaited_once_with(90, 2, 20)
    reader.assert_awaited_once_with(20, start, end, "hour")

    await service.usage_summary(90, 20, start_at=start, end_at=end + timedelta(seconds=1), tenant_id=2)
    assert reader.await_args.args[-1] == "day"
    for invalid_start, invalid_end in [
        (start.replace(tzinfo=None), end),
        (end, start),
        (start, start + timedelta(days=366, seconds=1)),
    ]:
        with pytest.raises(DshInvalidRequestError):
            await service.usage_summary(90, 20, start_at=invalid_start, end_at=invalid_end, tenant_id=2)
    assert authorize.await_count == 2

    await service.usage_summary(
        90, 20, start_at=start, end_at=start + timedelta(days=7), tenant_id=2, granularity="hour"
    )
    assert reader.await_args.args[-1] == "hour"
    await service.usage_summary(90, 20, start_at=start, end_at=end, tenant_id=2, granularity="day")
    assert reader.await_args.args[-1] == "day"
    for value, duration in [("minute", timedelta(days=1)), ("hour", timedelta(days=7, seconds=1))]:
        with pytest.raises(DshInvalidRequestError):
            await service.usage_summary(90, 20, start_at=start, end_at=start + duration, tenant_id=2, granularity=value)
    assert authorize.await_count == 4


async def test_usage_overview_service_authorizes_tenant_and_forwards_filters():
    authorize = AsyncMock(return_value=({}, None))
    reader = AsyncMock(
        return_value={
            "tenant_id": 2,
            "start_at": "2026-09-01T00:00:00+00:00",
            "end_at": "2026-09-08T00:00:00+00:00",
            "timezone": "Asia/Shanghai",
            "department_id": 10,
            "totals": {
                "message_count": 0,
                "qa_count": 0,
                "failed_count": 0,
                "cancelled_count": 0,
                "running_count": 0,
                "usage_unknown_count": 0,
                "recorded_usage_count": 0,
                "missing_usage_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }
    )
    service = DshManagementService(
        repository_scope=None,
        gateway=None,
        authorize=authorize,
        profiles=None,
        policy=None,
        policy_view=None,
        now=None,
        usage_overview_view=reader,
    )
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = start + timedelta(days=7)

    with profile_scope(2):
        await service.usage_overview(
            90,
            start_at=start,
            end_at=end,
            cursor=20,
            limit=10,
            keyword="ali",
            department_id=10,
        )
    authorize.assert_awaited_once_with(90, None)
    reader.assert_awaited_once_with(
        start_at=start,
        end_at=end,
        after_user_id=20,
        limit=10,
        keyword="ali",
        department_id=10,
        include_summary=False,
        granularity=None,
    )


async def test_usage_summary_route_passes_required_offset_timestamps():
    from bisheng.dsh.api.endpoints import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    service = SimpleNamespace(usage_summary=AsyncMock(return_value={"message_count": 3}))
    app.dependency_overrides[admin.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[admin.get_management] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dsh/admin/users/20/usage-summary",
            params={
                "tenant_id": 2,
                "start_at": "2026-09-01T00:00:00+08:00",
                "end_at": "2026-09-08T00:00:00+08:00",
            },
        )
        assert response.status_code == 200 and response.json()["data"] == {"message_count": 3}
        assert (await client.get("/api/v1/dsh/admin/users/20/usage-summary")).status_code == 422
    service.usage_summary.assert_awaited_once_with(
        90,
        20,
        start_at=datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=8))),
        end_at=datetime(2026, 9, 8, tzinfo=timezone(timedelta(hours=8))),
        tenant_id=2,
        granularity=None,
    )


@pytest.mark.parametrize("include_summary", [False, True])
@pytest.mark.parametrize("granularity", [None, "hour", "day"])
async def test_usage_overview_route_passes_department_and_search_filters(include_summary, granularity):
    from bisheng.dsh.api.endpoints import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    service = SimpleNamespace(usage_overview=AsyncMock(return_value={"items": []}))
    app.dependency_overrides[admin.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[admin.get_management] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dsh/admin/usage-overview",
            params={
                "tenant_id": 2,
                "start_at": "2026-09-01T00:00:00+08:00",
                "end_at": "2026-09-08T00:00:00+08:00",
                "cursor": "20",
                "limit": 10,
                "keyword": "ali",
                "department_id": 10,
                "include_summary": include_summary,
                **({"granularity": granularity} if granularity else {}),
            },
        )
    assert response.status_code == 200 and response.json()["data"] == {"items": []}
    service.usage_overview.assert_awaited_once_with(
        90,
        start_at=datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=8))),
        end_at=datetime(2026, 9, 8, tzinfo=timezone(timedelta(hours=8))),
        tenant_id=2,
        cursor=20,
        limit=10,
        keyword="ali",
        department_id=10,
        include_summary=include_summary,
        granularity=granularity,
    )
