"""Execute organization search and location against real SQL with scoped data."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.department import DepartmentPermissionDeniedError
from bisheng.department.domain.repositories.organization_search_repository import OrganizationSearchRepository
from bisheng.department.domain.services.organization_search_service import OrganizationSearchService
from test.department.test_global_members_search import _DDL


@pytest.fixture(autouse=True)
def directory_tenant(tenant_context):
    tenant_context(1)


@pytest.fixture
async def directory_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        for statement in _DDL:
            await connection.execute(text(statement.replace("user_name VARCHAR(255) UNIQUE", "user_name VARCHAR(255)")))
        await connection.execute(
            text("""INSERT INTO department (id, dept_id, name, parent_id, path, sort_order, status) VALUES
            (1,'root','Root',NULL,'/1/',0,'active'),
            (2,'visible','Product',1,'/1/2/',2,'active'),
            (3,'hidden','Private',1,'/1/3/',1,'active'),
            (4,'earlier','Earlier',2,'/1/2/4/',0,'active'),
            (5,'later','Later',2,'/1/2/5/',1,'active'),
            (6,'archived','Archived',2,'/1/2/6/',2,'archived')""")
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            yield session

    with patch("bisheng.department.domain.repositories.organization_search_repository.get_async_db_session", sessions):
        yield engine
    await engine.dispose()


async def add_user(engine, uid, name, memberships, *, disabled=False, external_id=None):
    async with engine.begin() as connection:
        await connection.execute(
            text('INSERT INTO user (user_id,user_name,"delete",external_id) VALUES (:id,:name,:disabled,:external)'),
            {"id": uid, "name": name, "disabled": int(disabled), "external": external_id},
        )
        for department_id, primary in memberships:
            await connection.execute(
                text("INSERT INTO user_department (user_id,department_id,is_primary) VALUES (:id,:dept,:primary)"),
                {"id": uid, "dept": department_id, "primary": primary},
            )


async def test_secondary_member_is_searchable_without_exposing_primary(directory_db):
    """AC-02/03: Any visible membership is sufficient; hidden paths never leave SQL projection."""
    await add_user(directory_db, 10, "Finance Ada", [(3, 1), (2, 0), (4, 0)])
    result = await OrganizationSearchRepository.members("Ada", 1, 20, {"/1/2/"}, False, 2)
    assert result["total"] == 1
    row = result["data"][0]
    assert not row["is_primary"]
    assert row["department"] == {
        "id": 2,
        "dept_id": "visible",
        "name": "Product",
        "status": "active",
        "path": "Product",
    }
    assert "Private" not in str(result)
    assert "Root" not in row["department"]["path"]


async def test_primary_precedes_preferred_secondary_and_fallback_uses_tree_order(directory_db):
    """AC-03: Primary, selected visible secondary, and tree ordering have deterministic precedence."""
    await add_user(directory_db, 10, "Ada", [(3, 1), (5, 0), (4, 0)])
    all_visible = await OrganizationSearchRepository.members("Ada", 1, 20, None, False, 5)
    assert all_visible["data"][0]["department"]["id"] == 3
    assert all_visible["data"][0]["is_primary"]
    preferred = await OrganizationSearchRepository.members("Ada", 1, 20, {"/1/2/"}, False, 5)
    assert preferred["data"][0]["department"]["id"] == 5
    fallback = await OrganizationSearchRepository.members("Ada", 1, 20, {"/1/2/"}, False, 3)
    assert fallback["data"][0]["department"]["id"] == 4


async def test_search_is_name_contains_only_with_literal_wildcards(directory_db):
    """AC-01: IDs are display data; percent and underscore are literal name characters."""
    await add_user(directory_db, 10, "prefix-Ada-suffix", [(2, 1)], external_id="identity-only")
    await add_user(directory_db, 11, "100%_name", [(2, 1)])
    assert (await OrganizationSearchRepository.members("Ada", 1, 20, None, False, None))["total"] == 1
    assert (await OrganizationSearchRepository.members("identity-only", 1, 20, None, False, None))["total"] == 0
    assert (await OrganizationSearchRepository.members("%_", 1, 20, None, False, None))["total"] == 1
    assert (await OrganizationSearchRepository.departments("visible", 1, 20, None, False))["total"] == 0


async def test_dedup_pagination_disabled_and_archived_scope(directory_db):
    """AC-02/04/10: Distinct users drive counts; disabled accounts remain findable."""
    for uid in range(1, 26):
        await add_user(directory_db, uid, "Same", [(2, 1), (4, 0)], disabled=uid == 25)
    result = await OrganizationSearchRepository.members("Same", 2, 20, {"/1/2/"}, False, None)
    assert result["total"] == 25
    assert len(result["data"]) == 5
    assert result["data"][-1]["enabled"] is False
    await add_user(directory_db, 30, "Archived person", [(6, 1)])
    assert (await OrganizationSearchRepository.members("Archived", 1, 20, None, False, None))["total"] == 0
    assert (await OrganizationSearchRepository.members("Archived", 1, 20, None, True, None))["total"] == 1
    assert (await OrganizationSearchRepository.members("Same", 3, 20, None, False, None)) == {"data": [], "total": 25}
    assert (await OrganizationSearchRepository.members("Same", 1, 20, set(), True, None))["total"] == 0


async def test_department_path_excludes_self_and_out_of_scope_ancestors(directory_db):
    """AC-04: The path contains only visible ancestors, never the leaf itself."""
    result = await OrganizationSearchRepository.departments("Earlier", 1, 20, {"/1/2/"}, False)
    assert result["data"][0]["parent_path"] == "Product"
    root = await OrganizationSearchRepository.departments("Root", 1, 20, None, False)
    assert root["data"][0]["parent_path"] == ""


async def test_location_uses_real_membership_order_and_only_resets_conflicting_filter(directory_db):
    """AC-07: Locate page 2 without scanning client pages, while preserving compatible filters."""
    for uid in range(1, 31):
        await add_user(directory_db, uid, f"User {uid}", [(2, uid % 2)])
    result = await OrganizationSearchRepository.member_location(2, 26, 20, 1)
    assert result == {"page": 2, "filter_adjusted": True, "is_primary_filter": None}
    compatible = await OrganizationSearchRepository.member_location(2, 27, 20, 1)
    assert compatible == {"page": 1, "filter_adjusted": False, "is_primary_filter": 1}
    assert await OrganizationSearchRepository.member_location(4, 27, 20, None) is None


async def test_service_rechecks_target_scope_and_missing_members(directory_db):
    """AC-11: A stale result cannot grant access to its former department."""
    await add_user(directory_db, 10, "Ada", [(3, 1), (2, 0)])
    with patch(
        "bisheng.department.domain.services.organization_search_service._aget_user_scope",
        AsyncMock(return_value=(False, {"/1/2/"})),
    ):
        with pytest.raises(DepartmentPermissionDeniedError):
            await OrganizationSearchService.locate_member(SimpleNamespace(), "hidden", 10, 20, None, False)
        result = await OrganizationSearchService.locate_member(SimpleNamespace(), "visible", 10, 20, 1, False)
        assert result["filter_adjusted"]


async def test_other_tenant_departments_are_excluded_even_without_path_filter(directory_db):
    """AC-02: A broad admin search still honors the injected tenant boundary."""
    async with directory_db.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO department (id,dept_id,name,path,tenant_id,status) VALUES (9,'other-tenant','Other tenant','/9/',2,'active')"
            )
        )
    await add_user(directory_db, 10, "Tenant isolated", [(9, 1)])
    result = await OrganizationSearchRepository.members("Tenant isolated", 1, 20, None, False, None)
    assert result["total"] == 0


async def test_http_search_and_locate_validate_membership_scope(directory_db):
    """AC-03/07/11: Exercise the endpoint/service/repository chain with real SQL."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.department.api.endpoints.organization_search import router

    await add_user(directory_db, 10, "Ada", [(3, 1), (2, 0)])
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/departments")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=42)
    with patch(
        "bisheng.department.domain.services.organization_search_service._aget_user_scope",
        AsyncMock(return_value=(False, {"/1/2/"})),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            found = (await client.get("/api/v1/departments/search/directory", params={"keyword": "Ada"})).json()
            assert found["status_code"] == 200
            assert found["data"]["data"][0]["department"]["name"] == "Product"
            allowed = (
                await client.get("/api/v1/departments/visible/members/locate", params={"user_id": 10, "is_primary": 1})
            ).json()
            assert allowed["data"]["filter_adjusted"]
            denied = (await client.get("/api/v1/departments/hidden/members/locate", params={"user_id": 10})).json()
            assert denied["status_code"] == 21009
