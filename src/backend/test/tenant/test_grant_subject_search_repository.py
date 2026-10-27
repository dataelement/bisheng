"""Execute candidate SQL with real data; permission scope is supplied by the service."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.group import Group
from bisheng.database.models.tenant import UserTenant
from bisheng.tenant.domain.repositories import grant_subject_search_repository as queries
from bisheng.tenant.domain.services.f048_permission_subject import TenantPermissionSubjectDirectory
from bisheng.user.domain.models.user import User


@pytest.fixture()
async def directory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        tables = [model.__table__ for model in (Department, User, UserTenant, UserDepartment, Group)]
        await conn.run_sync(lambda db: SQLModel.metadata.create_all(db, tables=tables))
        await conn.execute(
            Department.__table__.insert(),
            [
                {
                    "id": 1,
                    "dept_id": "BS@1",
                    "name": "root",
                    "external_id": "org-1",
                    "tenant_id": 1,
                    "path": "/1/",
                    "status": "active",
                },
                {
                    "id": 2,
                    "dept_id": "BS@2",
                    "name": "child",
                    "external_id": "org-2",
                    "tenant_id": 1,
                    "path": "/1/2/",
                    "status": "active",
                },
            ],
        )
        await conn.execute(
            User.__table__.insert(),
            [
                {
                    "user_id": 1,
                    "user_name": "jia0100",
                    "external_id": "jia0100",
                    "password": "test-only",
                    "source": "local",
                    "delete": 0,
                },
                {
                    "user_id": 2,
                    "user_name": "same",
                    "external_id": "jia0100-02",
                    "password": "test-only",
                    "source": "local",
                    "delete": 0,
                },
                {
                    "user_id": 3,
                    "user_name": "same",
                    "external_id": "jia0100",
                    "password": "test-only",
                    "source": "wecom",
                    "delete": 0,
                },
                {
                    "user_id": 4,
                    "user_name": "same",
                    "external_id": "jia-disabled",
                    "password": "test-only",
                    "source": "local",
                    "delete": 1,
                },
                {
                    "user_id": 5,
                    "user_name": "same",
                    "external_id": "jia-other",
                    "password": "test-only",
                    "source": "local",
                    "delete": 0,
                },
                {
                    "user_id": 6,
                    "user_name": "same",
                    "external_id": "jia-no-dept",
                    "password": "test-only",
                    "source": "local",
                    "delete": 0,
                },
            ],
        )
        await conn.execute(
            UserTenant.__table__.insert(),
            [
                {"user_id": uid, "tenant_id": 2 if uid == 5 else 1, "status": "active", "is_active": 1}
                for uid in range(1, 7)
            ],
        )
        await conn.execute(
            UserDepartment.__table__.insert(),
            [
                {"id": uid, "user_id": uid, "department_id": 1 if uid == 1 else 2, "is_primary": 1}
                for uid in range(1, 6)
            ],
        )
        await conn.execute(
            Group.__table__.insert(),
            [
                {"id": 12, "group_name": "a", "tenant_id": 1},
                {"id": 120, "group_name": "b", "tenant_id": 1},
                {"id": 121, "group_name": "c", "tenant_id": 2},
            ],
        )

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine) as db:
            yield db

    monkeypatch.setattr(queries, "get_async_db_session", session)
    yield TenantPermissionSubjectDirectory()
    await engine.dispose()


def scope(path=None):
    return SimpleNamespace(tenant_id=1, department_path=path)


async def test_grant_identity_scope_dedup_and_exact_before_page(directory):
    rows = await directory.candidate_users(scope(), keyword="jia0100", page=1, page_size=2)
    assert [row.user_id for row in rows] == [3, 1]
    assert await directory.count_candidate_users(scope(), keyword="jia0100") == 3
    rows = await directory.candidate_users(scope(), keyword="jia0100", page=2, page_size=2)
    assert [row.user_id for row in rows] == [2]
    assert await directory.candidate_users(scope(), keyword="0100", page=1, page_size=50) == []


async def test_historical_membership_is_not_a_grant_candidate(directory):
    async with queries.get_async_db_session() as session:
        session.add(UserTenant(user_id=5, tenant_id=1, status="active", is_active=None))
        await session.commit()
    rows = await directory.candidate_users(scope(), keyword="jia-other", page=1, page_size=50)
    assert rows == []
    assert await directory.count_candidate_users(scope(), keyword="jia-other") == 0


async def test_stale_selected_user_has_a_specific_membership_error(directory, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.common.errcode.permission import PermissionSubjectUnavailableError
    from bisheng.database.models.tenant import UserTenantDao

    monkeypatch.setattr(
        UserTenantDao,
        "aget_user_tenants",
        AsyncMock(
            return_value=[
                SimpleNamespace(tenant_id=1, status="active", is_active=None),
                SimpleNamespace(tenant_id=2, status="active", is_active=1),
            ]
        ),
    )
    with pytest.raises(PermissionSubjectUnavailableError):
        await directory.canonical_source(
            tenant_id=1, source_id=0, subject_type="user", subject_id="5", userset_relation=None, include_children=False
        )


async def test_flat_grants_preserve_mainline_department_and_disabled_scope(directory):
    rows = await directory.candidate_users(scope(), keyword="jia", page=1, page_size=50)
    assert {row.user_id for row in rows} == {1, 2, 3, 6}
    rows = await directory.candidate_users(scope("/1/2/"), keyword="jia", page=1, page_size=50)
    assert {row.user_id for row in rows} == {2, 3}


async def test_group_primary_key_prefix_and_true_total(directory):
    rows = await directory.candidate_groups(scope(), keyword="12", page=1, page_size=1)
    assert [row.id for row in rows] == [12]
    assert await directory.count_candidate_groups(scope(), keyword="12") == 2
    assert await directory.candidate_groups(scope(), keyword="012", page=1, page_size=50) == []


async def test_department_external_identity_not_internal_business_code(directory):
    assert [row.id for row in await directory.candidate_departments(scope(), keyword="org-2", limit=50)] == [2]
    assert await directory.candidate_departments(scope(), keyword="BS@2", limit=50) == []
